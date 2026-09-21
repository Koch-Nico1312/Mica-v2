"""Selbst-Quellcode-Zugriff: MICA liest ihren eigenen Code und ändert Einstellungen.

Dieses Modul gibt MICA kontrollierten Zugriff auf ihre eigene Installation:

- **Lesen** ist immer erlaubt, aber streng begrenzt: nur Dateien innerhalb des
  eigenen Wurzelverzeichnisses, nur bekannte Text-Endungen, nur bis zu einer
  Größe, und niemals Inhalte aus ``.git``, virtuellen Umgebungen oder Caches.
- **Geheimnisse werden maskiert.** Beim Lesen von ``.env``/``config/*.json``
  werden Werte, deren Schlüssel nach Secret aussieht, durch ``***gesetzt***``
  ersetzt — so landen API-Keys nie im Modellkontext oder im Log.
- **Einstellungen ändern** ist möglich, aber jeder Schreibvorgang
  (a) legt vorher ein Backup unter ``memory/self-edits/`` an,
  (b) protokolliert den Vorgang in einem append-only Index,
  (c) läuft über das Bestätigungs-Gate auf dem HUD und
  (d) ist über den Undo-Stack rückgängig zu machen.
- **Quellcode-Änderungen** sind zusätzlich durch ``MICA_SELF_EDIT_ENABLED=1``
  abgeschaltet, nur als eindeutige Literal-Ersetzung möglich, werden vor dem
  Schreiben syntaktisch geprüft (py_compile) und immer als Diff-Vorschau
  angeboten.

Bewusst NICHT enthalten: Ausführen von Code, Löschen von Dateien, Änderungen
außerhalb des eigenen Wurzelverzeichnisses, und alles, was die
Sicherheitsarchitektur (Policy, Freigaben, Audit) berührt.
"""

from __future__ import annotations

import difflib
import json
import os
import py_compile
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

MAX_READ_BYTES = 200_000
MAX_SEARCH_RESULTS = 60
MAX_LISTED_FILES = 400
TEXT_SUFFIXES = {".py", ".md", ".json", ".txt", ".toml", ".yml", ".yaml", ".ini", ".cfg", ".example"}
SKIP_DIRS = {
    ".git", ".venv", ".venv-local", ".venv-kokoro", ".venv-qwen-tts", ".uv-cache",
    "__pycache__", ".pytest_cache", "node_modules", "improvement-workspace", ".mica-data",
    "brag-output-2026-09-17-202833", ".benchmarks",
}
SECRET_MARKERS = ("api_key", "apikey", "token", "secret", "password", "passwd", "private_key", "authorization")


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def own_root() -> Path:
    """Wurzel der eigenen Installation (Tests können sie per Env umlenken)."""
    override = os.getenv("MICA_SELF_ROOT", "").strip()
    return Path(override).resolve() if override else get_base_dir().resolve()


def source_editing_enabled() -> bool:
    return os.getenv("MICA_SELF_EDIT_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _looks_secret(name: str) -> bool:
    lowered = str(name).lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _mask_env_line(line: str) -> str:
    match = re.match(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*)$", line)
    if not match:
        return line
    prefix, key, sep, value = match.groups()
    if not _looks_secret(key):
        return line
    return f"{prefix}{key}{sep}{'***gesetzt***' if value.strip() else '***leer***'}"


def _mask_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("***gesetzt***" if _looks_secret(str(key)) and value[key] else _mask_json(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mask_json(item) for item in value]
    return value


def _resolve(relative_path: str) -> Path:
    """Auflösen mit Pfad-Käfig: nichts außerhalb der eigenen Wurzel."""
    root = own_root()
    candidate = (root / str(relative_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("Pfad liegt außerhalb der eigenen Installation") from error
    if any(part in SKIP_DIRS for part in candidate.parts):
        raise ValueError("Dieser Bereich wird nicht gelesen (virtuelle Umgebung, Cache oder Git)")
    if candidate.suffix and candidate.suffix.lower() not in TEXT_SUFFIXES and not candidate.name.startswith(".env"):
        raise ValueError(f"Dateityp {candidate.suffix or '(ohne)'} wird nicht unterstützt")
    return candidate


@dataclass(frozen=True)
class _Backup:
    """A snapshot of one file, including whether the file existed at all."""

    path: Path
    existed: bool


def _backup(path: Path, label: str) -> _Backup:
    backup_dir = own_root() / "memory" / "self-edits"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"{stamp}-{path.name}.bak"
    existed = path.exists()
    backup.write_bytes(path.read_bytes() if existed else b"")
    index = backup_dir / "index.jsonl"
    with index.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "at": datetime.now().isoformat(timespec="seconds"),
            "file": str(path.relative_to(own_root())).replace("\\", "/"),
            "label": label[:200],
            "backup": backup.name,
            "existed": existed,
        }, ensure_ascii=False) + "\n")
    return _Backup(path=backup, existed=existed)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp",
    )
    try:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def _register_undo(path: Path, backup: _Backup, label: str) -> None:
    try:
        from core import undo as undo_stack

        def restore() -> str:
            if not backup.path.exists():
                return f"Kein Backup für {path.name} gefunden"
            if backup.existed:
                path.write_bytes(backup.path.read_bytes())
                return f"Wiederhergestellt: {path.name}"
            # The file did not exist before: restoring means removing it again,
            # not leaving an empty file behind.
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return f"Entfernt: {path.name} (existierte vorher nicht)"

        undo_stack.push_undo(f"Selbst-Änderung: {label}", restore)
    except Exception:
        pass  # Undo ist Komfort, nie Voraussetzung


# ── Lesen ────────────────────────────────────────────────────────────────────

def list_sources(limit: int = MAX_LISTED_FILES) -> list[dict[str, Any]]:
    root = own_root()
    found: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if len(found) >= max(1, min(int(limit), MAX_LISTED_FILES)):
            break
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found.append({
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "bytes": stat.st_size,
        })
    return found


def read_source(relative_path: str, max_bytes: int = MAX_READ_BYTES) -> dict[str, Any]:
    path = _resolve(relative_path)
    if not path.is_file():
        raise ValueError(f"Datei nicht gefunden: {relative_path}")
    raw = path.read_bytes()[: max(1, min(int(max_bytes), MAX_READ_BYTES))]
    text = raw.decode("utf-8", errors="replace")
    if path.name.startswith(".env") or _looks_secret(path.name):
        text = "\n".join(_mask_env_line(line) for line in text.splitlines())
    if path.suffix.lower() == ".json":
        try:
            text = json.dumps(_mask_json(json.loads(text)), ensure_ascii=False, indent=2)
        except (ValueError, json.JSONDecodeError):
            pass
    return {
        "path": str(path.relative_to(own_root())).replace("\\", "/"),
        "bytes": len(raw),
        "content": text,
    }


def search_source(term: str, limit: int = 20, extensions: list[str] | None = None) -> list[dict[str, Any]]:
    needle = str(term).strip()
    if len(needle) < 2:
        raise ValueError("Suchbegriff muss mindestens 2 Zeichen haben")
    allowed = {ext if ext.startswith(".") else f".{ext}" for ext in (extensions or [])}
    results: list[dict[str, Any]] = []
    for entry in list_sources(MAX_LISTED_FILES):
        if allowed and Path(entry["path"]).suffix.lower() not in allowed:
            continue
        try:
            data = read_source(entry["path"], MAX_READ_BYTES)
        except ValueError:
            continue
        for number, line in enumerate(data["content"].splitlines(), 1):
            if needle.lower() in line.lower():
                results.append({
                    "path": entry["path"], "line": number,
                    "excerpt": _mask_env_line(line.strip())[:220],
                })
                break
        if len(results) >= max(1, min(int(limit), MAX_SEARCH_RESULTS)):
            break
    return results


# ── Einstellungen ────────────────────────────────────────────────────────────

def _env_paths() -> tuple[Path, Path]:
    root = own_root()
    return root / ".env", root / ".env.example"


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def list_settings(mask_secrets: bool = True) -> dict[str, Any]:
    env, example = _env_paths()
    current = _parse_env(env)
    documented = list(_parse_env(example).keys())
    items: list[dict[str, Any]] = []
    for key in sorted(set(documented) | set(current)):
        value = current.get(key, "")
        items.append({
            "key": key,
            "value": "***gesetzt***" if (mask_secrets and _looks_secret(key)) else value,
            "set": bool(value),
            "documented": key in documented,
        })
    configs = []
    config_dir = own_root() / "config"
    if config_dir.is_dir():
        for path in sorted(config_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            keys = sorted(data) if isinstance(data, dict) else []
            configs.append({
                "file": str(path.relative_to(own_root())).replace("\\", "/"),
                "keys": [
                    {"key": key, "set": bool(data.get(key)), "value": "***gesetzt***" if mask_secrets and data.get(key) else ""}
                    for key in keys
                ],
            })
    return {"env_file": str(env.relative_to(own_root())) if env.exists() else "", "settings": items, "configs": configs}


def _setting_target(key: str) -> Path:
    env, example = _env_paths()
    if key in _parse_env(env) or key in _parse_env(example):
        return env
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ValueError("Ungültiger Einstellungsname")
    if _parse_env(example) and key not in _parse_env(example):
        known = ", ".join(sorted(_parse_env(example))[:12])
        raise ValueError(f"Unbekannte Einstellung '{key}'. Dokumentiert sind z. B.: {known}")
    return env


def preview_setting(key: str, value: str) -> dict[str, Any]:
    key = str(key).strip()
    target = _setting_target(key)
    old_line = ""
    if target.is_file():
        for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
            if re.match(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=", line):
                old_line = line
                break
    new_line = f"{key}={value}"
    return {
        "file": str(target.relative_to(own_root())).replace("\\", "/"),
        "key": key,
        "old": _mask_env_line(old_line) or "(nicht gesetzt)",
        "new": _mask_env_line(new_line),
        "diff": "\n".join(difflib.unified_diff(
            [old_line or ""], [new_line], fromfile="vorher", tofile="nachher", lineterm="",
        )),
    }


def apply_setting(key: str, value: str) -> dict[str, Any]:
    preview = preview_setting(key, value)
    target = own_root() / preview["file"]
    lines: list[str] = []
    if target.is_file():
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        example = own_root() / ".env.example"
        if example.is_file():
            lines = example.read_text(encoding="utf-8", errors="replace").splitlines()
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
    replaced = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    backup = _backup(target, f"{key} setzen")
    _atomic_write(target, "\n".join(lines).rstrip("\n") + "\n")
    _register_undo(target, backup, f"{key} setzen")
    return {**preview, "written": True, "backup": backup.path.name}


# ── Quellcode-Änderung ───────────────────────────────────────────────────────

def preview_source_edit(relative_path: str, old_text: str, new_text: str) -> dict[str, Any]:
    path = _resolve(relative_path)
    if not path.is_file():
        raise ValueError(f"Datei nicht gefunden: {relative_path}")
    if not old_text.strip():
        raise ValueError("Der zu ersetzende Text darf nicht leer sein")
    content = path.read_text(encoding="utf-8", errors="replace")
    occurrences = content.count(old_text)
    if occurrences != 1:
        raise ValueError(
            f"Der Suchtext kommt {occurrences}x vor — Änderungen sind nur bei genau einem Treffer erlaubt"
        )
    updated = content.replace(old_text, new_text, 1)
    if path.suffix.lower() == ".py":
        try:
            compile(updated, str(path), "exec")
        except SyntaxError as error:
            raise ValueError(f"Die Änderung wäre kein gültiges Python: {error}") from error
    return {
        "path": str(path.relative_to(own_root())).replace("\\", "/"),
        "occurrences": occurrences,
        "diff": "\n".join(difflib.unified_diff(
            content.splitlines(), updated.splitlines(),
            fromfile=f"a/{relative_path}", tofile=f"b/{relative_path}", lineterm="",
        ))[:8000],
        "updated": updated,
    }


def apply_source_edit(relative_path: str, old_text: str, new_text: str) -> dict[str, Any]:
    if not source_editing_enabled():
        return {
            "written": False,
            "reason": "Quellcode-Änderungen sind aus. Setze MICA_SELF_EDIT_ENABLED=1, um sie zu erlauben.",
        }
    preview = preview_source_edit(relative_path, old_text, new_text)
    path = _resolve(relative_path)
    backup = _backup(path, f"Quelländerung in {preview['path']}")
    _atomic_write(path, preview["updated"])
    if path.suffix.lower() == ".py":
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as error:
            path.write_bytes(backup.path.read_bytes())  # sofort zurückrollen
            raise ValueError(f"Kompilierung fehlgeschlagen — Änderung zurückgerollt: {error}") from error
    _register_undo(path, backup, f"Quelländerung in {preview['path']}")
    return {
        "written": True, "path": preview["path"], "backup": backup.path.name,
        "diff": preview["diff"],
    }


def edit_history(limit: int = 20) -> list[dict[str, Any]]:
    index = own_root() / "memory" / "self-edits" / "index.jsonl"
    if not index.is_file():
        return []
    entries = []
    for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entries.append(json.loads(line))
        except (ValueError, json.JSONDecodeError):
            continue
    return entries[-max(1, min(int(limit), 100)) :][::-1]


# ── Tool-Einstiegspunkt ──────────────────────────────────────────────────────

CONFIRM_ACTIONS = {"apply_setting", "apply_edit"}


def self_source_action(
    parameters: dict[str, Any],
    response: Any = None,
    player: Any = None,
    confirm_request: Callable[[str, str, str, Callable[[], str]], str] | None = None,
) -> str:
    """MICA-Tool: eigener Quellcode lesen und Einstellungen ändern."""
    action = str(parameters.get("action", "")).strip().lower()
    try:
        if action == "list":
            files = list_sources()
            return "Eigene Dateien (Auszug):\n" + "\n".join(
                f"- {item['path']} ({item['bytes']} B)" for item in files[:80]
            )
        if action == "read":
            data = read_source(str(parameters.get("path", "")))
            return f"{data['path']} ({data['bytes']} B):\n\n{data['content'][:12000]}"
        if action == "search":
            hits = search_source(str(parameters.get("term", "")), int(parameters.get("limit", 20) or 20))
            if not hits:
                return f"Keine Treffer für '{parameters.get('term')}'."
            return "Treffer:\n" + "\n".join(f"- {h['path']}:{h['line']}: {h['excerpt']}" for h in hits)
        if action == "settings":
            data = list_settings()
            lines = [f"- {item['key']} = {item['value'] or '(nicht gesetzt)'}" for item in data["settings"][:60]]
            return "Einstellungen:\n" + "\n".join(lines)
        if action == "history":
            entries = edit_history()
            if not entries:
                return "Ich habe noch keine eigenen Änderungen protokolliert."
            return "Letzte eigene Änderungen:\n" + "\n".join(
                f"- {e['at']} {e['file']} ({e['label']})" for e in entries
            )
        if action == "preview_setting":
            data = preview_setting(str(parameters.get("key", "")), str(parameters.get("value", "")))
            return f"So würde ich {data['file']} ändern:\n\n{data['diff'] or data['old'] + ' -> ' + data['new']}"
        if action == "preview_edit":
            data = preview_source_edit(
                str(parameters.get("path", "")), str(parameters.get("old_text", "")), str(parameters.get("new_text", "")),
            )
            return f"Vorschlag für {data['path']}:\n\n{data['diff']}"
        if action in CONFIRM_ACTIONS:
            key = str(parameters.get("key", ""))
            path = str(parameters.get("path", ""))
            label = f"Einstellung {key}" if action == "apply_setting" else f"Quelländerung {path}"

            def run() -> str:
                if action == "apply_setting":
                    data = apply_setting(key, str(parameters.get("value", "")))
                    return f"Einstellung {data['key']} in {data['file']} geändert (Backup: {data['backup']})."
                data = apply_source_edit(path, str(parameters.get("old_text", "")), str(parameters.get("new_text", "")))
                if not data.get("written"):
                    return f"Nicht geändert: {data.get('reason', 'abgelehnt')}"
                return f"{data['path']} geändert (Backup: {data['backup']})."

            gate = confirm_request
            if gate is None:
                try:
                    from core import confirm as confirm_gate

                    gate = confirm_gate.request
                except Exception:
                    gate = None
            if gate is None:
                return "Ich kann das gerade nicht bestätigen lassen (kein HUD gebunden) — es wurde nichts geändert."
            return gate(
                f"self-source:{action}:{key or path}",
                f"Eigene Änderung: {label}",
                "MICA ändert eine eigene Datei. Vorher wird ein Backup angelegt; danach ist 'undo' möglich.",
                run,
            )
        return (
            "Unbekannte Aktion. Erlaubt: list, read, search, settings, history, "
            "preview_setting, preview_edit, apply_setting, apply_edit."
        )
    except ValueError as error:
        return f"self_source: {error}"
