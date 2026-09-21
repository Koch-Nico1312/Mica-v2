"""Read-only Phase-0 readiness probe for the supported Windows desktop path."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from typing import Any


def _command(arguments: list[str], timeout: int = 15) -> dict[str, Any]:
    executable = shutil.which(arguments[0])
    if not executable:
        return {"ok": False, "reason": "not_found", "command": arguments[0]}
    try:
        completed = subprocess.run(
            [executable, *arguments[1:]], capture_output=True, text=True,
            timeout=timeout, check=False, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "reason": type(error).__name__, "detail": str(error)[:300]}
    detail = (completed.stdout or completed.stderr).strip()
    return {"ok": completed.returncode == 0, "returncode": completed.returncode, "detail": detail[:1000]}


def _port_available(port: int) -> dict[str, Any]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return {"ok": True, "port": port}
    except OSError as error:
        return {"ok": False, "port": port, "reason": str(error)}
    finally:
        sock.close()


def _bitlocker(path: Path) -> dict[str, Any]:
    drive = path.resolve().drive
    if not drive:
        return {"ok": False, "reason": "path_has_no_windows_drive"}
    result = _command(["manage-bde", "-status", drive])
    text = str(result.get("detail", "")).lower()
    encrypted = any(marker in text for marker in (
        "fully encrypted", "vollständig verschlüsselt", "vollstaendig verschluesselt",
    ))
    protected = any(marker in text for marker in (
        "protection on", "schutz aktiviert", "protection status:    protection on",
    ))
    if result["ok"]:
        result["ok"] = encrypted and protected
        result["encrypted"] = encrypted
        result["protected"] = protected
        if not result["ok"]:
            result["reason"] = "bitlocker_not_fully_protected"
    else:
        result["reason"] = "bitlocker_unverified"
    result["drive"] = drive
    return result


def _credential_manager() -> dict[str, Any]:
    try:
        import keyring  # type: ignore[import-not-found]

        backend = keyring.get_keyring()
        name = f"{backend.__class__.__module__}.{backend.__class__.__name__}"
        priority = float(getattr(backend, "priority", 0))
        windows_backend = "windows" in name.lower() or "winvault" in name.lower()
        return {"ok": windows_backend and priority > 0, "backend": name, "priority": priority}
    except Exception as error:
        return {"ok": False, "reason": "credential_manager_unavailable", "detail": str(error)[:300]}


def _audio() -> dict[str, Any]:
    try:
        import sounddevice  # type: ignore[import-not-found]

        devices = sounddevice.query_devices()
        inputs = sum(1 for device in devices if int(device.get("max_input_channels", 0)) > 0)
        outputs = sum(1 for device in devices if int(device.get("max_output_channels", 0)) > 0)
        return {"ok": inputs > 0 and outputs > 0, "inputs": inputs, "outputs": outputs}
    except Exception as error:
        return {"ok": False, "reason": "audio_probe_failed", "detail": str(error)[:300]}


def _storage(path: Path, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    existing = resolved if resolved.exists() else resolved.parent
    free = shutil.disk_usage(existing).free if existing.exists() else 0
    return {
        "ok": existing.exists() and os.access(existing, os.R_OK | os.W_OK) and free >= 5 * 1024**3,
        "label": label,
        "path": str(resolved),
        "exists": resolved.exists(),
        "free_gib": round(free / 1024**3, 2),
    }


def _caddy(environ: dict[str, str]) -> dict[str, Any]:
    candidates = [
        shutil.which("caddy"),
        str(Path(environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "caddy.exe"),
    ]
    executable = next((item for item in candidates if item and Path(item).is_file()), None)
    return _command([executable or "caddy", "version"])


def _firewall() -> dict[str, Any]:
    script = (
        "$names=@('MICA Windows Host Agent block LAN TCP','MICA Windows Host Agent block LAN UDP');"
        "$valid=0;foreach($name in $names){$rule=Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue;"
        "if($rule -and $rule.Enabled -eq 'True' -and $rule.Direction -eq 'Inbound' -and $rule.Action -eq 'Block'){"
        "$port=$rule|Get-NetFirewallPortFilter;if($port.LocalPort -eq '9443'){$valid++}}};"
        "if($valid -eq 2){Write-Output 'TCP and UDP LAN block rules active';exit 0};"
        "Write-Output ('Expected 2 active block rules, found '+$valid);exit 1"
    )
    result = _command(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
    if not result.get("ok"):
        result["reason"] = "firewall_rules_missing_or_invalid"
    return result


def _models(data_dir: Path, environ: dict[str, str]) -> dict[str, Any]:
    names = {
        "llama": environ.get("LLAMA_MODEL", ""),
        "whisper": environ.get("WHISPER_MODEL", ""),
        "piper": environ.get("PIPER_MODEL", ""),
    }
    paths = {name: data_dir / "models" / value for name, value in names.items() if value}
    missing = [name for name in names if not names[name] or not paths[name].is_file()]
    return {"ok": not missing, "paths": {name: str(path) for name, path in paths.items()}, "missing": missing}


def _tls_material(certificate: Path | None) -> dict[str, Any]:
    if certificate is None:
        return {"ok": False, "reason": "tls_certificate_not_configured", "path": ""}
    host_crt = certificate.expanduser().resolve()
    directory = host_crt.parent
    required = {
        "host_certificate": host_crt,
        "host_key": directory / "host.key",
        "broker_ca": directory / "broker-ca.crt",
        "client_certificate": directory / "client.crt",
        "client_key": directory / "client.key",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        return {
            "ok": False, "reason": "tls_material_missing", "path": str(host_crt),
            "missing": missing,
        }
    openssl_candidates = [
        shutil.which("openssl"),
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
    ]
    openssl = next((item for item in openssl_candidates if item and Path(item).is_file()), None)
    if not openssl:
        return {"ok": False, "reason": "openssl_not_found", "path": str(host_crt)}
    verify = _command([
        openssl, "verify", "-CAfile", str(required["broker_ca"]),
        str(required["host_certificate"]), str(required["client_certificate"]),
    ])
    host_text = _command([openssl, "x509", "-in", str(host_crt), "-noout", "-subject", "-ext", "subjectAltName"])
    client_text = _command([
        openssl, "x509", "-in", str(required["client_certificate"]),
        "-noout", "-subject", "-ext", "extendedKeyUsage",
    ])
    host_detail = str(host_text.get("detail", ""))
    client_detail = str(client_text.get("detail", ""))
    identities_ok = (
        "DNS:host.docker.internal" in host_detail
        and "CN=mica-tool-broker" in client_detail
        and "TLS Web Client Authentication" in client_detail
    )
    return {
        "ok": bool(verify.get("ok")) and identities_ok,
        "path": str(host_crt),
        "chain_verified": bool(verify.get("ok")),
        "identities_verified": identities_ok,
        "detail": str(verify.get("detail", ""))[:1000],
    }


def check(
    data_dir: Path,
    backup_dir: Path,
    *,
    certificate: Path | None = None,
    ports: tuple[int, ...] = (443, 9443),
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    docker = _command(["docker", "info", "--format", "{{json .ServerVersion}}"], timeout=20)
    compose = _command(["docker", "compose", "version"])
    checks: dict[str, Any] = {
        "docker_daemon": docker,
        "docker_compose": compose,
        "caddy": _caddy(env),
        "firewall": _firewall(),
        "models": _models(data_dir, env),
        "audio": _audio(),
        "credential_manager": _credential_manager(),
        "data_storage": _storage(data_dir, "data"),
        "backup_storage": _storage(backup_dir, "backup"),
        "data_bitlocker": _bitlocker(data_dir),
        "backup_bitlocker": _bitlocker(backup_dir),
        "certificate": _tls_material(certificate),
        "ports": {str(port): _port_available(port) for port in ports},
        "legacy_ollama": {**_command(["ollama", "--version"]), "required": False},
    }
    required = [name for name in checks if name != "legacy_ollama"]
    ready = all(
        all(item.get("ok", False) for item in value.values()) if name == "ports" else bool(value.get("ok"))
        for name, value in checks.items() if name in required
    )
    return {
        "schema_version": 1, "platform": "windows", "checked_at": datetime.now(UTC).isoformat(),
        "ready": ready, "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="MICA Phase-0 Windows readiness probe")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--ports", type=int, nargs="*", default=[443, 9443])
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence file")
    arguments = parser.parse_args()
    result = check(
        arguments.data_dir, arguments.backup_dir,
        certificate=arguments.certificate, ports=tuple(arguments.ports),
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.output:
        destination = arguments.output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, destination)
    print(encoded)
    return 1 if arguments.strict and not result["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
