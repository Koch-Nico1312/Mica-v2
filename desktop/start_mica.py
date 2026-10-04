"""One Windows entrypoint: prepare the local Core, then open the desktop UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable

from desktop.core.secure_store import get_secret, set_secret
from desktop.core.settings_store import _read_env, _update_env

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def docker_ready(docker: str) -> bool:
    return subprocess.run(
        [docker, "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=10, **HIDDEN,
    ).returncode == 0


def ensure_docker() -> None:
    docker = shutil.which("docker")
    if not docker:
        cli = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe"
        docker = str(cli) if cli.is_file() else ""
    executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/Docker Desktop.exe"
    if not executable.is_file():
        executable = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/Docker Desktop.exe"
    if not docker:
        raise RuntimeError("Docker Desktop fehlt. Bitte Docker Desktop installieren.")
    try:
        if docker_ready(docker):
            return
    except subprocess.TimeoutExpired:
        pass
    if not executable.is_file():
        raise RuntimeError("Docker Desktop.exe wurde nicht gefunden. Bitte Docker Desktop installieren.")
    print("Docker Desktop wird gestartet ...", flush=True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    subprocess.Popen([str(executable)], startupinfo=startup)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if docker_ready(docker):
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2)
    raise RuntimeError("Docker Desktop ist nicht bereit. Bitte dessen Fehlermeldung pruefen.")


def prepare_local_config() -> dict[str, str]:
    backend_env = ROOT / "backend/.env"
    if not backend_env.is_file():
        shutil.copyfile(ROOT / "backend/.env.example", backend_env)
        _update_env(backend_env, {
            "MICA_DATA_DIR": (ROOT / ".mica-data").as_posix(),
            "MICA_PUBLIC_HOST": "localhost", "MICA_HTTPS_PORT": "8443", "MICA_HTTP_PORT": "8080",
        })
    mapping_path = ROOT / "desktop/config/credential-names.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.is_file() else {}
    for name in ("MICA_API_TOKEN", "MICA_APPROVAL_SECRET"):
        credential = mapping.get(name, name)
        value = get_secret(credential)
        if not value:
            value = secrets.token_urlsafe(48)
            set_secret(credential, value)
        if name == "MICA_API_TOKEN" and credential != name:
            set_secret(name, value)
        mapping[name] = credential
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    settings = _read_env(backend_env)
    if not settings.get("MICA_MODELS_DIR"):
        models = ROOT / "desktop/models"
        if (models / settings.get("LLAMA_MODEL", "Qwen3-4B-Q4_K_M.gguf")).is_file():
            _update_env(backend_env, {"MICA_MODELS_DIR": models.as_posix()})
    settings = _read_env(backend_env)
    base_host = settings.get("MICA_PUBLIC_HOST", "localhost")
    if base_host not in {"localhost", "127.0.0.1", "mica.local"}:
        raise RuntimeError("Der lokale Desktop-Starter benoetigt localhost, 127.0.0.1 oder mica.local in MICA_PUBLIC_HOST.")
    origin = f"https://{base_host}"
    https_port = settings.get("MICA_HTTPS_PORT", "443")
    if https_port != "443":
        origin += f":{https_port}"
    allowed_origins = [item.strip().rstrip("/") for item in settings.get("MICA_ALLOWED_VOICE_ORIGINS", "").split(",") if item.strip()]
    if origin not in allowed_origins:
        allowed_origins.append(origin)
        _update_env(backend_env, {"MICA_ALLOWED_VOICE_ORIGINS": ",".join(allowed_origins)})
    if not settings.get("MICA_LAN_PASSWORD_HASH"):
        password = get_secret("MICA_LAN_PASSWORD")
        if not password:
            password = secrets.token_urlsafe(24)
            set_secret("MICA_LAN_PASSWORD", password)
        caddy = shutil.which("caddy")
        command = ([caddy] if caddy else [shutil.which("docker"), "run", "--rm", "caddy:2.8-alpine"])
        result = subprocess.run(
            [*command, "hash-password", "--plaintext", password],
            capture_output=True, text=True, check=True, **HIDDEN,
        )
        _update_env(backend_env, {"MICA_LAN_PASSWORD_HASH": "'" + result.stdout.strip() + "'"})
    return _read_env(backend_env)


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def start_host_agent(settings: dict[str, str]) -> None:
    """Start an already configured agent; never grant additional actions."""
    if not settings.get("MICA_HOST_AGENT_URL"):
        return
    config_path = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Mica/windows-host-agent.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "desktop"), str(ROOT / "backend")])
    environment["MICA_WINDOWS_ENABLED_ACTIONS"] = ",".join(config.get("allowed_actions", []))
    logs = ROOT / ".mica-data/startup"
    logs.mkdir(parents=True, exist_ok=True)
    if not port_open(8766):
        with (logs / "host-agent.log").open("ab") as log:
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.windows_host_agent.app:app",
                 "--host", "127.0.0.1", "--port", "8766"],
                cwd=ROOT, env=environment, stdout=log, stderr=log, **HIDDEN,
            )
    if not port_open(9443):
        caddy = shutil.which("caddy")
        if not caddy:
            raise RuntimeError("Caddy fuer den konfigurierten Windows-Aktionsdienst fehlt.")
        with (logs / "host-proxy.log").open("ab") as log:
            subprocess.Popen(
                [caddy, "run", "--config", str(ROOT / "backend/windows_host_agent/Caddyfile.mtls.example"),
                 "--adapter", "caddyfile"], cwd=ROOT, stdout=log, stderr=log, **HIDDEN,
            )


def start_core(progress: Callable[[str], None] = print) -> dict:
    progress("docker")
    ensure_docker()
    progress("configuration")
    settings = prepare_local_config()
    progress("host")
    start_host_agent(settings)
    enabled = {**settings, **_read_env(ROOT / ".env")}
    command = [sys.executable, "-m", "backend.windows_launcher"]
    if enabled.get("MICA_HINDSIGHT_ENABLED", "").lower() in {"1", "true", "yes", "on"}:
        command.append("--hindsight")
    progress("services")
    subprocess.run(
        [*command, "--", "up", "-d", "--wait", "--wait-timeout", "300"], cwd=ROOT, check=True,
        **HIDDEN,
    )
    progress("connection")
    data = Path(settings["MICA_DATA_DIR"])
    ca = data / "caddy/caddy/pki/authorities/local/root.crt"
    if not ca.is_file():
        raise RuntimeError("Das HTTPS-Zertifikat fehlt. Bitte den Caddy-Dienst pruefen.")
    host = settings.get("MICA_PUBLIC_HOST", "localhost")
    port = settings.get("MICA_HTTPS_PORT", "443")
    url = f"https://{host}" + (f":{port}" if port != "443" else "")
    from desktop.core.local_core_client import LocalCoreClient
    client = LocalCoreClient(base_url=url, ca_file=ca)
    try:
        health = client.health()
    finally:
        client.session.close()
    _update_env(ROOT / ".env", {"MICA_CORE_URL": url, "MICA_CORE_CA_FILE": ca.as_posix()})
    os.environ["MICA_CORE_URL"] = url
    os.environ["MICA_CORE_CA_FILE"] = str(ca)
    return health


def main(*, console: bool = False) -> int:
    try:
        if console:
            start_core()
        else:
            from desktop.startup_window import run_startup
            if not run_startup(start_core, ROOT):
                return 1
        # Keep exactly the interpreter and entrypoint used by the working PS command.
        return subprocess.run([sys.executable, str(ROOT / "desktop/local_main.py")], cwd=ROOT / "desktop").returncode
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        # Subprocess exceptions may contain credential-bearing command arguments.
        print(f"MICA konnte nicht gestartet werden ({type(error).__name__}).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(console="--console" in sys.argv))
