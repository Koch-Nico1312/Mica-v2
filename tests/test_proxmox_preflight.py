from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "mica_core"
sys.path.insert(0, str(ROOT))

import preflight


class ProxmoxPreflightTests(unittest.TestCase):
    def test_https_origin_rejects_non_origin_inputs(self):
        self.assertTrue(preflight._https_input("https://mica.example.lan")["passed"])
        for value in ("http://mica.example.lan", "https://user@mica.example.lan", "https://mica.example.lan/path", "https://mica.example.lan/?x=1"):
            with self.subTest(value=value):
                self.assertFalse(preflight._https_input(value)["passed"])

    def test_lxc_requires_explicit_acknowledgement_and_never_certifies_gpu(self):
        lxc = {"detected": "lxc", "is_vm": False, "is_lxc": True, "detail": "lxc"}
        self.assertFalse(preflight._target_check("proxmox-lxc", lxc, False)["passed"])
        self.assertTrue(preflight._target_check("proxmox-lxc", lxc, True)["passed"])

    def test_port_probe_reports_a_real_listener_as_in_use(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("0.0.0.0", 0))
        listener.listen(1)
        try:
            result = preflight._port_probe(listener.getsockname()[1])
        finally:
            listener.close()
        self.assertFalse(result["passed"])
        self.assertEqual(result["state"], "in_use")

    def test_vm_report_checks_compose_resources_time_dns_ports_and_nvidia_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            compose = root / "docker-compose.yml"
            environment = root / ".env"
            lxc_override = root / "docker-compose.lxc.yml"
            compose.write_text("services: {}\n", encoding="utf-8")
            lxc_override.write_text("services: {}\n", encoding="utf-8")
            environment.write_text("MICA_DATA_DIR=/srv/mica\n", encoding="utf-8")
            commands = iter([
                (True, "27.0"),  # docker info
                (True, "v2.30"),  # docker compose version
                (True, ""),  # docker compose config --quiet
                (True, ""),  # container volume probe
                (True, "yes"),  # timedatectl
                (True, '{"nvidia":{"path":"nvidia-container-runtime"}}'),  # runtimes
            ])
            with (
                patch("preflight.shutil.which", return_value="/usr/bin/docker"),
                patch("preflight._command", side_effect=lambda *args, **kwargs: next(commands)),
                patch("preflight._virtualization_probe", return_value={"detected": "kvm", "is_vm": True, "is_lxc": False, "detail": "kvm"}),
                patch("preflight._hardware", return_value={"cpu_logical": 4, "memory_bytes": 16 * 1024 ** 3}),
                patch("preflight._port_probe", side_effect=lambda port: {"port": port, "passed": True, "state": "available", "detail": "test"}),
                patch("preflight._dns_probe", return_value=(True, "192.0.2.10")),
                patch("preflight._https_probe", return_value=(True, "HTTP 200 with trusted certificate")),
            ):
                report = preflight.check(
                    data, [], public_url="https://mica.example.lan", target="proxmox-vm",
                    compose_files=[compose, lxc_override], env_file=environment,
                )
        self.assertTrue(report["deployment_target"]["passed"])
        self.assertTrue(report["compose"]["available"])
        self.assertEqual(report["compose"]["files"], [str(compose), str(lxc_override)])
        self.assertTrue(report["compose"]["config_passed"])
        self.assertTrue(report["resources"]["passed"])
        self.assertTrue(report["time"]["passed"])
        self.assertTrue(report["dns"]["passed"])
        self.assertTrue(report["https"]["input"]["passed"])
        self.assertTrue(report["nvidia_runtime"]["passed"])

    def test_lxc_gpu_request_is_reported_as_unsupported_even_when_guest_checks_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            commands = iter([
                (True, "27.0"), (True, "v2.30"), (True, ""), (True, "GPU"),
                (True, "yes"), (True, '{"nvidia":{}}'),
            ])
            with (
                patch("preflight.shutil.which", return_value="/usr/bin/docker"),
                patch("preflight._command", side_effect=lambda *args, **kwargs: next(commands)),
                patch("preflight._virtualization_probe", return_value={"detected": "lxc", "is_vm": False, "is_lxc": True, "detail": "lxc"}),
                patch("preflight._hardware", return_value={"cpu_logical": 4, "memory_bytes": 16 * 1024 ** 3}),
                patch("preflight._port_probe", return_value={"port": 443, "passed": True, "state": "available", "detail": "test"}),
            ):
                report = preflight.check(Path(temporary) / "data", [], gpu_probe=True, target="proxmox-lxc", lxc_acknowledged=True)
        self.assertTrue(report["deployment_target"]["passed"])
        self.assertFalse(report["gpu_target_compatible"]["passed"])


if __name__ == "__main__":
    unittest.main()
