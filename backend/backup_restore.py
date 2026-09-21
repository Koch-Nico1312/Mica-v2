"""Create and verify a recoverable backup of MICA's authoritative truth.

The disposable SQLite search index is deliberately *not* treated as backup
truth.  A drill restores Markdown plus the hash-chained audit log into a fresh
directory and rebuilds the index there.  No source data is changed by a drill.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.common.audit import AuditLog
from services.common.brain import MarkdownBrain


SCHEMA_VERSION = 2
ARCHIVE_PREFIX = "mica-truth"
ARCHIVE_MEMBERS = {"manifest.json", "state/phase4.json"}


def _state_export(data_dir: Path) -> bytes:
    """Export durable task/plan/twin state without treating SQLite as archive truth."""
    database = data_dir / "scheduler.sqlite3"
    tables = (
        "task_items", "schedules", "automation_rules", "automation_firings",
        "agent_plans", "agent_plan_steps", "agent_plan_corrections",
        "server_observations", "server_diagnostics", "digital_twin_settings",
        "digital_twin_facts", "digital_twin_evidence", "presence_state", "improvement_signals",
    )
    exported: dict[str, list[dict[str, Any]]] = {}
    if database.is_file():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in tables:
                if table in existing:
                    exported[table] = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
        finally:
            connection.close()
    configuration: dict[str, Any] = {}
    for name in ("profile.json", "domains.json"):
        path = data_dir / name
        if path.is_file() and not path.is_symlink():
            try:
                configuration[name] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
    return (json.dumps({
        "schema_version": 1, "created_at": datetime.now(UTC).isoformat(),
        "tables": exported, "configuration": configuration,
    }, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


class BackupDrillError(RuntimeError):
    """The backup was not created or could not prove a clean restore."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _truth_files(data_dir: Path) -> list[Path]:
    """Return only Markdown truth and its audit trail, never SQLite/cache data."""
    files: list[Path] = []
    brain = data_dir / "brain"
    if brain.is_dir():
        files.extend(path for path in brain.rglob("*.md") if path.is_file() and not path.is_symlink())
    audit = data_dir / "audit" / "events.jsonl"
    if audit.is_file() and not audit.is_symlink():
        files.append(audit)
    return sorted(files, key=lambda path: path.relative_to(data_dir).as_posix())


def _manifest(data_dir: Path) -> dict[str, Any]:
    audit_path = data_dir / "audit" / "events.jsonl"
    if audit_path.exists() and not AuditLog(audit_path).verify():
        raise BackupDrillError("source audit hash chain is invalid; refusing to back it up as verified truth")
    files = _truth_files(data_dir)
    return {
        "schema": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "truth": "Markdown and hash-chained audit; SQLite is rebuilt during restore",
        "files": [
            {"path": path.relative_to(data_dir).as_posix(), "sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in files
        ],
        "audit_present": audit_path.is_file(),
    }


def create_backup(data_dir: Path, backup_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Atomically archive source truth and return its immutable manifest."""
    data_dir = data_dir.resolve()
    backup_dir = backup_dir.resolve()
    if not data_dir.is_dir():
        raise BackupDrillError("MICA data directory does not exist")
    try:
        backup_dir.relative_to(data_dir)
    except ValueError:
        pass
    else:
        raise BackupDrillError("backup target must be outside the live MICA data directory")
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not backup_dir.is_dir():
        raise BackupDrillError("backup target is not a directory")
    manifest = _manifest(data_dir)
    state_export = _state_export(data_dir)
    manifest["state_export"] = {
        "path": "state/phase4.json", "sha256": hashlib.sha256(state_export).hexdigest(), "bytes": len(state_export),
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = backup_dir / f"{ARCHIVE_PREFIX}-{timestamp}.tar.gz"
    suffix = 1
    while archive.exists():
        archive = backup_dir / f"{ARCHIVE_PREFIX}-{timestamp}-{suffix}.tar.gz"
        suffix += 1
    temporary = backup_dir / f".{archive.name}.partial"
    try:
        with tarfile.open(temporary, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
            encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(encoded)
            info.mtime = int(datetime.now(UTC).timestamp())
            info.mode = 0o600
            bundle.addfile(info, io.BytesIO(encoded))
            state_info = tarfile.TarInfo("state/phase4.json")
            state_info.size = len(state_export)
            state_info.mtime = info.mtime
            state_info.mode = 0o600
            bundle.addfile(state_info, io.BytesIO(state_export))
            for record in manifest["files"]:
                source = data_dir / record["path"]
                bundle.add(source, arcname=record["path"], recursive=False)
        os.replace(temporary, archive)
    except (OSError, tarfile.TarError) as error:
        temporary.unlink(missing_ok=True)
        raise BackupDrillError(f"could not create backup archive: {error}") from error
    return archive, manifest


def _safe_extract(archive: Path, destination: Path) -> dict[str, Any]:
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            for member in members:
                name = Path(member.name)
                if member.issym() or member.islnk() or name.is_absolute() or ".." in name.parts:
                    raise BackupDrillError("archive contains an unsafe member")
                if member.name not in ARCHIVE_MEMBERS and not member.name.startswith("brain/") and member.name != "audit/events.jsonl":
                    raise BackupDrillError(f"archive member is outside MICA truth scope: {member.name}")
            manifest_member = bundle.extractfile("manifest.json")
            if manifest_member is None:
                raise BackupDrillError("archive has no manifest")
            manifest = json.loads(manifest_member.read().decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("schema") not in {1, SCHEMA_VERSION} or not isinstance(manifest.get("files"), list):
                raise BackupDrillError("archive manifest has an unsupported schema")
            for record in manifest["files"]:
                if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                    raise BackupDrillError("archive manifest contains an invalid file record")
                member = bundle.getmember(record["path"])
                source = bundle.extractfile(member)
                if source is None:
                    raise BackupDrillError("archive member cannot be read")
                target = destination / record["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            if manifest.get("schema") == SCHEMA_VERSION:
                state_record = manifest.get("state_export")
                if not isinstance(state_record, dict):
                    raise BackupDrillError("archive manifest has no Phase-4 state export")
                state_member = bundle.extractfile("state/phase4.json")
                if state_member is None:
                    raise BackupDrillError("archive has no Phase-4 state export")
                state_bytes = state_member.read()
                if len(state_bytes) != state_record.get("bytes") or hashlib.sha256(state_bytes).hexdigest() != state_record.get("sha256"):
                    raise BackupDrillError("Phase-4 state export hash does not match")
                state_payload = json.loads(state_bytes.decode("utf-8"))
                if state_payload.get("schema_version") != 1 or not isinstance(state_payload.get("tables"), dict):
                    raise BackupDrillError("Phase-4 state export has an unsupported schema")
                state_target = destination / "state" / "phase4.json"
                state_target.parent.mkdir(parents=True, exist_ok=True)
                state_target.write_bytes(state_bytes)
    except (OSError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
        raise BackupDrillError(f"could not restore backup archive: {error}") from error
    return manifest


def _rebuild_state_export(destination: Path) -> dict[str, int]:
    """Rebuild supported local state into a fresh SQLite database from JSON truth."""
    export_path = destination / "state" / "phase4.json"
    if not export_path.is_file():
        return {}
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    tables = payload.get("tables", {})
    if not isinstance(tables, dict):
        raise BackupDrillError("Phase-4 state export tables are invalid")
    from services.common.phase4 import Phase4Store
    from services.common.scheduler_store import ScheduleStore
    from services.common.task_automation import TaskAutomationStore

    database = destination / "state" / "scheduler.sqlite3"
    ScheduleStore(database)
    TaskAutomationStore(database)
    Phase4Store(database)
    allowed_tables = {
        "task_items", "schedules", "automation_rules", "automation_firings",
        "agent_plans", "agent_plan_steps", "agent_plan_corrections",
        "server_observations", "server_diagnostics", "digital_twin_settings",
        "digital_twin_facts", "digital_twin_evidence", "presence_state", "improvement_signals",
    }
    restored_counts: dict[str, int] = {}
    connection = sqlite3.connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in allowed_tables:
            rows = tables.get(table, [])
            if not isinstance(rows, list):
                raise BackupDrillError(f"Phase-4 state table is invalid: {table}")
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            for row in rows:
                if not isinstance(row, dict) or not row or not set(row).issubset(columns):
                    raise BackupDrillError(f"Phase-4 state row is invalid: {table}")
                names = list(row)
                quoted = ",".join(f'"{name}"' for name in names)
                placeholders = ",".join("?" for _ in names)
                connection.execute(
                    f'INSERT OR REPLACE INTO "{table}"({quoted}) VALUES({placeholders})',
                    tuple(row[name] for name in names),
                )
            restored_counts[table] = len(rows)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    for name, value in payload.get("configuration", {}).items():
        if name not in {"profile.json", "domains.json"}:
            continue
        (destination / "state" / name).write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8",
        )
    return restored_counts


def verify_restore(archive: Path) -> dict[str, Any]:
    """Restore into a disposable location, validate source hashes and rebuild SQLite."""
    if not archive.is_file():
        raise BackupDrillError("backup archive does not exist")
    with tempfile.TemporaryDirectory(prefix="mica-restore-drill-") as temporary:
        restored = Path(temporary)
        manifest = _safe_extract(archive, restored)
        for record in manifest["files"]:
            target = restored / record["path"]
            if not target.is_file() or target.stat().st_size != record["bytes"] or _sha256(target) != record["sha256"]:
                raise BackupDrillError(f"restored content hash does not match: {record['path']}")
        audit = AuditLog(restored / "audit" / "events.jsonl")
        if not audit.verify():
            raise BackupDrillError("restored audit hash chain is invalid")
        brain = MarkdownBrain(restored / "brain", restored / "index" / "brain.sqlite3")
        document_count = brain.reindex()
        restored_state = _rebuild_state_export(restored)
        connection = sqlite3.connect(brain.index_path)
        try:
            chunk_count = int(connection.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0])
            vector_count = int(connection.execute("SELECT COUNT(*) FROM document_vectors").fetchone()[0])
        finally:
            connection.close()
        if chunk_count != vector_count:
            raise BackupDrillError("rebuilt FTS and vector index disagree")
        return {
            "passed": True,
            "archive": str(archive),
            "truth_files": len(manifest["files"]),
            "markdown_documents": document_count,
            "fts_chunks": chunk_count,
            "audit_valid": True,
            "sqlite_rebuilt": brain.index_path.is_file(),
            "state_export_valid": (restored / "state" / "phase4.json").is_file(),
            "state_sqlite_rebuilt": (restored / "state" / "scheduler.sqlite3").is_file(),
            "restored_state_rows": sum(restored_state.values()),
        }


def run_drill(data_dir: Path, backup_dir: Path) -> dict[str, Any]:
    archive, manifest = create_backup(data_dir, backup_dir)
    report = verify_restore(archive)
    report["archive_sha256"] = _sha256(archive)
    report["source_audit_present"] = bool(manifest["audit_present"])
    report_path = archive.with_suffix("").with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="MICA Markdown/audit backup and disposable restore drill")
    parser.add_argument("--data-dir", default=os.getenv("MICA_DATA_DIR", "/DATA/AppData/mica"))
    parser.add_argument("--backup-dir", required=True, help="Persistent backup target, distinct from MICA_DATA_DIR")
    parser.add_argument("--verify", metavar="ARCHIVE", help="Only validate and rebuild one existing archive")
    arguments = parser.parse_args()
    try:
        result = verify_restore(Path(arguments.verify)) if arguments.verify else run_drill(Path(arguments.data_dir), Path(arguments.backup_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BackupDrillError as error:
        print(json.dumps({"passed": False, "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
