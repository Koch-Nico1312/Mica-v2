"""Launch Docker Compose with secrets read from Windows Credential Manager.

Configuration maps a small allowlist of environment variable names to
Credential Manager entry names. Secret values are passed only in the child
process environment and are never printed or written to an env file.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Sequence

from core.secure_store import get_secret


ALLOWED_SECRET_ENV = {
    "MICA_APPROVAL_SECRET",
    "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    "MICA_TELEGRAM_BOT_TOKEN", "MICA_TELEGRAM_WEBHOOK_SECRET",
    "MICA_WHATSAPP_ACCESS_TOKEN", "MICA_WHATSAPP_VERIFY_TOKEN", "MICA_WHATSAPP_APP_SECRET",
    "MICA_PUSH_TOKEN", "MICA_PUSH_WEBHOOK_SECRET",
    "MICA_SIP_ARI_USER", "MICA_SIP_ARI_PASSWORD", "MICA_SIP_WEBHOOK_SECRET",
}


def credential_environment(config_path: Path) -> dict[str, str]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - ALLOWED_SECRET_ENV:
        raise ValueError("Credential-name configuration contains an unsupported environment variable")
    result: dict[str, str] = {}
    for env_name, credential_name in data.items():
        if not isinstance(credential_name, str):
            raise ValueError("Credential names must be strings")
        secret = get_secret(credential_name)
        if not secret:
            raise ValueError(f"Credential Manager entry is missing for {env_name}")
        result[env_name] = secret
    return result


def _docker_executable() -> str:
    discovered = shutil.which("docker")
    if discovered:
        return discovered
    if os.name == "nt":
        candidate = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("Docker CLI is not installed or is not on PATH")


def run_compose(config_path: Path, arguments: Sequence[str]) -> int:
    environment = dict(os.environ)
    environment.update(credential_environment(config_path))
    compose_root = Path(__file__).resolve().parent
    env_files = ["--env-file", ".env"]
    if (compose_root / ".env.phase4").is_file():
        env_files.extend(["--env-file", ".env.phase4"])
    completed = subprocess.run(
        [_docker_executable(), "compose", *env_files, *arguments],
        cwd=compose_root, env=environment, shell=False, check=False,
    )
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Start MICA without plaintext provider secrets")
    parser.add_argument(
        "--credentials", type=Path,
        default=Path(os.getenv("MICA_CREDENTIAL_NAMES", "config/credential-names.json")),
    )
    parser.add_argument("compose_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    compose_args = list(args.compose_args)
    if compose_args[:1] == ["--"]:
        compose_args = compose_args[1:]
    if not compose_args:
        compose_args = ["up", "-d", "--build"]
    return run_compose(args.credentials, compose_args)


if __name__ == "__main__":
    raise SystemExit(main())
