"""Deployment preflight for the local MICA Compose stack.

All checks are read-only except the explicitly requested ``--backup-drill``.
That option creates one timestamped backup archive and restores it only into a
temporary directory in order to prove that the SQLite index is disposable.

The same Compose file is used on ZimaOS and on a Linux guest in Proxmox.  A
full VM is the supported Proxmox path, particularly when CUDA is required:
the guest owns Docker, its NVIDIA driver, and the NVIDIA Container Toolkit.
An LXC can be used only for a CPU-only, explicitly acknowledged experimental
deployment; this probe deliberately does not certify GPU access from an LXC.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import platform
import shutil
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from backup_restore import BackupDrillError, run_drill


def _command(*parts: str, timeout: int = 12) -> tuple[bool, str]:
    try:
        result = subprocess.run(parts, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode == 0, (result.stdout or result.stderr).strip()[-500:]
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)


def _https_probe(url: str) -> tuple[bool, str]:
    if not url:
        return False, "not requested"
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=8, context=ssl.create_default_context()) as response:
            return 200 <= response.status < 500, f"HTTP {response.status} with trusted certificate"
    except (urllib.error.URLError, ValueError, TimeoutError) as error:
        return False, str(error)[-500:]


def _https_input(url: str) -> dict[str, object]:
    """Validate the origin before a network request can hide a bad setting."""
    if not url:
        return {"configured": False, "passed": False, "detail": "not requested", "hostname": ""}
    parsed = urlparse(url)
    valid = (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and parsed.path in ("", "/")
    )
    detail = "valid HTTPS origin" if valid else "must be an HTTPS origin without credentials, path, query, or fragment"
    return {"configured": True, "passed": valid, "detail": detail, "hostname": parsed.hostname or ""}


def _dns_probe(hostname: str) -> tuple[bool, str]:
    if not hostname:
        return False, "not requested"
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, None)})
        return bool(addresses), ", ".join(addresses[:8])
    except socket.gaierror as error:
        return False, str(error)


def _time_sync_probe() -> tuple[bool, str]:
    """Use systemd's status when available; wall-clock time alone is not proof."""
    for property_name in ("NTPSynchronized", "SystemClockSynchronized"):
        ok, detail = _command("timedatectl", "show", "--property", property_name, "--value")
        if ok:
            value = detail.strip().lower()
            return value == "yes", f"{property_name}={detail.strip()}"
    return False, "timedatectl synchronization status unavailable"


def _port_probe(port: int) -> dict[str, object]:
    if not 1 <= port <= 65535:
        return {"port": port, "passed": False, "state": "invalid", "detail": "port must be 1 through 65535"}
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("0.0.0.0", port))
        return {"port": port, "passed": True, "state": "available", "detail": "bind probe succeeded"}
    except OSError as error:
        if error.errno in (errno.EADDRINUSE, 10048):
            return {"port": port, "passed": False, "state": "in_use", "detail": str(error)}
        if error.errno in (errno.EACCES, 13, 10013):
            # Docker normally binds privileged ports as root.  A non-root
            # preflight process therefore cannot decide whether the port is
            # free, so report an honest warning instead of a false conflict.
            return {"port": port, "passed": True, "state": "permission_unverified", "detail": str(error)}
        return {"port": port, "passed": False, "state": "unavailable", "detail": str(error)}
    finally:
        probe.close()


def _virtualization_probe() -> dict[str, object]:
    ok, detail = _command("systemd-detect-virt")
    detected = detail.strip().lower() if ok else "unknown"
    return {
        "detected": detected,
        "is_vm": detected in {"kvm", "qemu"},
        "is_lxc": detected == "lxc",
        "detail": detail if ok else "systemd-detect-virt unavailable",
    }


def _hardware() -> dict[str, object]:
    cpu_logical = os.cpu_count()
    memory_bytes: int | None = None
    try:
        import psutil
        cpu_logical = psutil.cpu_count()
        memory_bytes = psutil.virtual_memory().total
    except ImportError:
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    memory_bytes = int(line.split()[1]) * 1024
                    break
        except (OSError, ValueError, IndexError):
            pass
    return {"cpu_logical": cpu_logical, "memory_bytes": memory_bytes}


def _resource_check(hardware: dict[str, object], min_cpu: int, min_memory_gib: int) -> dict[str, object]:
    memory_bytes = hardware.get("memory_bytes")
    cpu_ok = isinstance(hardware.get("cpu_logical"), int) and int(hardware["cpu_logical"]) >= min_cpu
    memory_ok = isinstance(memory_bytes, int) and memory_bytes >= min_memory_gib * 1024 ** 3
    return {
        "minimum_cpu_logical": min_cpu,
        "minimum_memory_gib": min_memory_gib,
        "cpu_passed": cpu_ok,
        "memory_passed": memory_ok,
        "passed": cpu_ok and memory_ok,
        "detail": "MICA baseline only; model/context settings can require more memory or VRAM",
    }


def _target_check(target: str, virtualization: dict[str, object], lxc_acknowledged: bool) -> dict[str, object]:
    if target == "proxmox-vm":
        passed = bool(virtualization["is_vm"])
        detail = (
            "KVM/QEMU guest detected; Proxmox ownership cannot be proven from inside the guest"
            if passed else "expected a KVM/QEMU Linux guest; run this inside the Proxmox VM"
        )
    elif target == "proxmox-lxc":
        passed = bool(virtualization["is_lxc"]) and lxc_acknowledged
        detail = (
            "experimental CPU-only LXC path acknowledged; Docker nesting, storage and device mappings remain host-admin checks"
            if passed else "requires an LXC guest and --acknowledge-lxc-constraints; use a VM for NVIDIA/CUDA"
        )
    else:
        passed, detail = True, "platform-neutral/ZimaOS deployment"
    return {"target": target, "passed": passed, "detail": detail}


def check(
    data_dir: Path,
    model_names: list[str],
    gpu_probe: bool = False,
    public_url: str = "",
    backup_dir: Path | None = None,
    llama_load_test: bool = False,
    gpu_layers: int = 12,
    backup_drill: bool = False,
    *,
    target: str = "auto",
    lxc_acknowledged: bool = False,
    ports: list[int] | None = None,
    min_cpu: int = 4,
    min_memory_gib: int = 16,
    compose_file: Path | None = None,
    compose_files: list[Path] | None = None,
    env_file: Path | None = None,
) -> dict[str, object]:
    models = data_dir / "models"
    docker_present = bool(shutil.which("docker"))
    docker_ok, docker_detail = _command("docker", "info", "--format", "{{.ServerVersion}}") if docker_present else (False, "docker command not found")
    compose_ok, compose_detail = _command("docker", "compose", "version", "--short") if docker_ok else (False, "docker unavailable")
    effective_compose_files = compose_files if compose_files is not None else ([compose_file] if compose_file else [])
    compose_config_ok, compose_config_detail = (False, "not requested")
    if compose_ok and effective_compose_files and all(path.is_file() for path in effective_compose_files) and env_file and env_file.is_file():
        compose_parts = ["docker", "compose", "--env-file", str(env_file)]
        for path in effective_compose_files:
            compose_parts.extend(("-f", str(path)))
        compose_parts.extend(("config", "--quiet"))
        compose_config_ok, compose_config_detail = _command(*compose_parts)
    elif effective_compose_files:
        compose_config_detail = "compose config skipped: provide an existing --env-file with required variables"
    container_write_ok, container_write_detail = (False, "docker unavailable")
    if docker_ok:
        container_write_ok, container_write_detail = _command(
            "docker", "run", "--rm", "--user", "65532:65532", "-v", f"{data_dir.resolve()}:/data",
            "python:3.12-slim", "python", "-c",
            "from pathlib import Path; p=Path('/data/.mica-container-write-probe'); p.write_text('ok'); p.unlink()",
            timeout=180,
        )
    gpu_present = Path("/dev/nvidia0").exists() or bool(shutil.which("nvidia-smi"))
    gpu_container_ok, gpu_container_detail = (False, "not requested")
    if gpu_probe and docker_ok:
        gpu_container_ok, gpu_container_detail = _command(
            "docker", "run", "--rm", "--gpus", "all", "nvidia/cuda:12.6.3-base-ubuntu24.04",
            "nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader", timeout=180,
        )
    llama_ok, llama_detail = (False, "not requested")
    llama_model = next((name for name in model_names if name.lower().endswith(".gguf")), "")
    if llama_load_test and docker_ok and llama_model and (models / llama_model).is_file():
        llama_ok, llama_detail = _command(
            "docker", "run", "--rm", "--gpus", "all", "-v", f"{models.resolve()}:/models:ro",
            "ghcr.io/ggml-org/llama.cpp:full-cuda", "--run", "-m", f"/models/{llama_model}",
            "-p", "Antworte nur mit OK.", "-n", "8", "--n-gpu-layers", str(max(0, gpu_layers)), timeout=300,
        )
    required_models = {name: (models / name).is_file() for name in model_names if name}
    writable = False
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".mica-preflight-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        pass
    https_input = _https_input(public_url)
    dns_ok, dns_detail = _dns_probe(str(https_input["hostname"])) if https_input["passed"] else (False, "HTTPS input invalid or not requested")
    https_ok, https_detail = _https_probe(public_url) if https_input["passed"] else (False, str(https_input["detail"]))
    backup_present = bool(backup_dir and backup_dir.is_dir())
    backup_result: dict[str, object] = {
        "configured": bool(backup_dir), "target_exists": backup_present,
        "path": str(backup_dir or ""), "drill_requested": backup_drill,
        "drill_passed": False, "detail": "not requested",
    }
    if backup_drill:
        if backup_dir is None:
            backup_result["detail"] = "--backup-drill requires --backup-dir"
        else:
            try:
                drill = run_drill(data_dir, backup_dir)
                backup_result.update({"target_exists": True, "drill_passed": bool(drill.get("passed")), "detail": drill})
            except BackupDrillError as error:
                backup_result["detail"] = str(error)
    hardware = _hardware()
    try:
        hardware["data_free_bytes"] = shutil.disk_usage(data_dir).free
    except OSError:
        hardware["data_free_bytes"] = None
    virtualization = _virtualization_probe()
    target_result = _target_check(target, virtualization, lxc_acknowledged)
    resource_result = _resource_check(hardware, min_cpu, min_memory_gib)
    checked_ports = [_port_probe(port) for port in (ports if ports is not None else [80, 443])]
    time_ok, time_detail = _time_sync_probe()
    nvidia_runtime_ok, nvidia_runtime_detail = _command("docker", "info", "--format", "{{json .Runtimes}}") if docker_ok else (False, "docker unavailable")
    nvidia_runtime_registered = nvidia_runtime_ok and "nvidia" in nvidia_runtime_detail.lower()
    gpu_requested = gpu_probe or llama_load_test
    gpu_target_ok = target != "proxmox-lxc" or not gpu_requested
    return {
        "data_dir": str(data_dir), "volume_writable": writable,
        "docker": {"available": docker_ok, "detail": docker_detail},
        "compose": {"available": compose_ok, "detail": compose_detail, "files": [str(path) for path in effective_compose_files], "config_checked": bool(effective_compose_files), "config_passed": compose_config_ok, "config_detail": compose_config_detail},
        "container_volume_writable": {"passed": container_write_ok, "detail": container_write_detail},
        "deployment_target": target_result,
        "virtualization": virtualization,
        "ports": checked_ports,
        "resources": resource_result,
        "dns": {"requested": bool(https_input["configured"]), "passed": dns_ok, "detail": dns_detail},
        "time": {"passed": time_ok, "detail": time_detail, "checked_at_utc": datetime.now(timezone.utc).isoformat()},
        "nvidia_detected": gpu_present,
        "nvidia_runtime": {"passed": nvidia_runtime_registered, "detail": nvidia_runtime_detail},
        "gpu_target_compatible": {"passed": gpu_target_ok, "detail": "LXC GPU passthrough is not a supported MICA path; use a Proxmox VM" if not gpu_target_ok else "compatible with the selected deployment target"},
        "nvidia_container_probe": {"requested": gpu_probe, "passed": gpu_container_ok, "detail": gpu_container_detail},
        "llama_gpu_load_test": {"requested": llama_load_test, "passed": llama_ok, "model": llama_model, "gpu_layers": gpu_layers, "detail": llama_detail},
        "models": required_models,
        "https": {"requested": bool(public_url), "input": https_input, "passed": https_ok, "detail": https_detail},
        "backup": backup_result,
        "hardware": {"platform": platform.platform(), "hostname": socket.gethostname(), **hardware},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MICA ZimaOS/Proxmox Linux preflight (read-only except explicit --backup-drill)")
    parser.add_argument("--data-dir", default=os.getenv("MICA_DATA_DIR", "/DATA/AppData/mica"))
    parser.add_argument("--models", nargs="*", default=[os.getenv("LLAMA_MODEL", ""), os.getenv("WHISPER_MODEL", ""), os.getenv("PIPER_MODEL", "")])
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--gpu-probe", action="store_true", help="Run nvidia-smi in a temporary CUDA container")
    parser.add_argument("--public-url", default="", help="HTTPS URL whose certificate and response should be checked")
    parser.add_argument("--backup-dir", default="", help="Persistent backup target directory")
    parser.add_argument("--backup-drill", action="store_true", help="Create a truth backup and prove disposable restore/index rebuild (writes only to backup target)")
    parser.add_argument("--llama-load-test", action="store_true", help="Load the configured GGUF in llama.cpp and generate eight tokens")
    parser.add_argument("--gpu-layers", type=int, default=int(os.getenv("LLAMA_GPU_LAYERS", "12")))
    parser.add_argument("--target", choices=("auto", "proxmox-vm", "proxmox-lxc"), default="auto", help="Proxmox VM is the supported CUDA/Docker target; LXC is explicit CPU-only experimental mode")
    parser.add_argument("--acknowledge-lxc-constraints", action="store_true", help="Required with --target proxmox-lxc; does not certify Docker nesting or GPU devices")
    parser.add_argument("--ports", type=int, nargs="*", default=[80, 443], help="Host TCP ports Compose/Caddy needs to publish")
    parser.add_argument("--min-cpu", type=int, default=4, help="Minimum logical CPUs required for the MICA baseline")
    parser.add_argument("--min-memory-gib", type=int, default=16, help="Minimum RAM in GiB required for the MICA baseline")
    parser.add_argument("--compose-file", action="append", default=[], help="Compose file to validate; repeat to validate an override (default: docker-compose.yml)")
    parser.add_argument("--env-file", default=".env", help="Deployment environment file used for docker compose config")
    arguments = parser.parse_args()
    report = check(
        Path(arguments.data_dir), arguments.models, arguments.gpu_probe, arguments.public_url,
        Path(arguments.backup_dir) if arguments.backup_dir else None, arguments.llama_load_test,
        arguments.gpu_layers, arguments.backup_drill, target=arguments.target,
        lxc_acknowledged=arguments.acknowledge_lxc_constraints, ports=arguments.ports,
        min_cpu=arguments.min_cpu, min_memory_gib=arguments.min_memory_gib,
        compose_files=[Path(path) for path in arguments.compose_file] or [Path(__file__).with_name("docker-compose.yml")],
        env_file=Path(arguments.env_file) if arguments.env_file else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    strict_failed = (
        not report["volume_writable"] or not report["docker"]["available"] or not report["compose"]["available"] or not report["container_volume_writable"]["passed"] or not all(report["models"].values())
        or not report["deployment_target"]["passed"] or not report["resources"]["passed"] or not report["time"]["passed"]
        or any(not port["passed"] for port in report["ports"])
        or (bool(report["compose"]["files"] and arguments.env_file and Path(arguments.env_file).is_file()) and not report["compose"]["config_passed"])
        or (arguments.gpu_probe and not report["nvidia_container_probe"]["passed"])
        or ((arguments.gpu_probe or arguments.llama_load_test) and (not report["nvidia_runtime"]["passed"] or not report["gpu_target_compatible"]["passed"]))
        or (arguments.llama_load_test and not report["llama_gpu_load_test"]["passed"])
        or (bool(arguments.public_url) and (not report["https"]["input"]["passed"] or not report["dns"]["passed"] or not report["https"]["passed"]))
        or (bool(arguments.backup_dir) and (not report["backup"]["target_exists"] or not report["backup"]["drill_passed"]))
    )
    if arguments.strict and strict_failed:
        raise SystemExit(2)
