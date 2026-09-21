"""Controlled end-to-end acceptance for MICA's Docker learning loop.

This runs the broker and real host-agent handler in process.  Its Docker
subprocess is deliberately made to return Docker's non-zero result, so it is
safe on a development machine: no container is created, stopped, or removed.
The TLS transport itself is represented by the verified-proxy headers the host
agent requires; production mTLS/Caddy still needs a separate deployment test.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient


CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))


class _DockerResult:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode, self._stdout, self._stderr = returncode, stdout, stderr

    def communicate(self, timeout: int) -> tuple[str, str]:
        return self._stdout, self._stderr

    def poll(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


class _InProcessMtlsHost:
    """Exercise host-agent validation while making the Docker outcome safe."""

    def __init__(self, host_module, trace: list[str]):
        self.host_module, self.trace = host_module, trace
        self.returncode = 1
        self.evidence = ""
        self.calls = 0

    def execute(self, action: str, params: dict[str, object], approval_id: str | None) -> dict[str, object]:
        self.trace.append("host-agent")
        self.calls += 1
        stderr = "Error response from daemon: No such container: mica-acceptance-missing\n"
        process = _DockerResult(self.returncode, "started mica-acceptance-missing\n" if not self.returncode else "", stderr if self.returncode else "")
        from datetime import UTC, datetime, timedelta

        request = self.host_module.ScopedRequest(
            request_id=uuid.uuid4().hex, scope=action, params=params,
            approval_id=approval_id, expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
        )
        with patch.object(self.host_module.subprocess, "Popen", return_value=process):
            try:
                return self.host_module.execute(request, "SUCCESS", "CN=mica-broker")
            except HTTPException as error:
                self.evidence = str(error.detail)
                raise


class DockerLearningAcceptanceTests(unittest.TestCase):
    @contextmanager
    def broker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "host-agent-config.json"
            config.write_text(json.dumps({
                "trusted_broker_subject": "CN=mica-broker",
                "allowed_scopes": ["docker.lifecycle"],
                "allowed_containers": ["mica-acceptance-missing"],
            }), encoding="utf-8")
            environment = {
                "BRAIN_DIR": str(root / "brain"), "INDEX_PATH": str(root / "index.sqlite3"),
                "AUDIT_PATH": str(root / "audit" / "events.jsonl"),
                "APPROVAL_DB": str(root / "approvals.sqlite3"), "CONNECTOR_DB": str(root / "connectors.sqlite3"),
                "MICA_HOST_AGENT_CONFIG": str(config), "MICA_HOST_AGENT_REPLAY_DB": str(root / "replay.sqlite3"),
            }
            with patch.dict(os.environ, environment, clear=False):
                broker_module = importlib.import_module("services.tool_broker")
                broker_module = importlib.reload(broker_module)
                host_module = importlib.import_module("host_agent.app")
                host_module.CONFIG_PATH = config
                host_module.REPLAY_DB = root / "replay.sqlite3"
                host_module._EMERGENCY_STOPPED = False
                with TestClient(broker_module.app) as client:
                    yield client, broker_module, host_module

    @staticmethod
    def _approve(client: TestClient, broker_module, payload: dict[str, object]) -> str:
        response = client.post("/v1/tools/call", json=payload)
        if response.status_code != 403:
            raise AssertionError(f"expected a fresh destructive approval, got {response.status_code}: {response.text}")
        approval_id = response.json()["detail"]["approval_id"]
        if not broker_module.policy.resolve(approval_id, True):
            raise AssertionError("test approval could not be resolved")
        return approval_id

    def test_failure_evidence_lesson_retrieval_and_repeat_are_traceable(self):
        payload = {"task_id": "a" * 32, "action": "docker.lifecycle", "params": {"operation": "start", "container": "mica-acceptance-missing"}}
        with self.broker() as (client, broker_module, host_module):
            trace: list[str] = []
            host = _InProcessMtlsHost(host_module, trace)
            original_search = broker_module.brain.search

            def traced_search(*args, **kwargs):
                trace.append("retrieval")
                return original_search(*args, **kwargs)

            approval_id = self._approve(client, broker_module, payload)
            with patch.object(broker_module.brain, "search", side_effect=traced_search), patch.object(broker_module.HostAgentClient, "from_environment", return_value=host):
                failed = client.post("/v1/tools/call", json={**payload, "approval_id": approval_id})
            self.assertEqual(failed.status_code, 502)
            self.assertEqual(trace[0], "retrieval")
            self.assertEqual(trace[-1], "host-agent")
            self.assertEqual(host.evidence, "Error response from daemon: No such container: mica-acceptance-missing\n")

            evidence = next(item for item in broker_module.brain.documents() if item["kind"] == "evidence")
            lesson = next(item for item in broker_module.brain.documents() if item["kind"] == "lessons")
            stored_source = Path(evidence["path"]).read_text(encoding="utf-8").split("---\n", 2)[2][1:]
            self.assertEqual(stored_source, host.evidence)
            self.assertEqual(evidence["sha256"], hashlib.sha256(host.evidence.encode("utf-8")).hexdigest())
            self.assertIn(f"[[{evidence['id']}]]", lesson["body"])
            self.assertIn("Reproduktion/Testentwurf", lesson["body"])

            # A retry requires a second human approval.  The broker must recall
            # the new Lesson before it reaches the host agent, but it never
            # silently changes the already approved Docker parameters.
            retry_payload = {**payload, "task_id": "b" * 32}
            retry_approval = self._approve(client, broker_module, retry_payload)
            host.returncode = 0
            trace.clear()
            with patch.object(broker_module.brain, "search", side_effect=traced_search), patch.object(broker_module.HostAgentClient, "from_environment", return_value=host):
                repeated = client.post("/v1/tools/call", json={**retry_payload, "approval_id": retry_approval})
            self.assertEqual(repeated.status_code, 200)
            result = repeated.json()
            self.assertEqual(trace[0], "retrieval")
            self.assertEqual(trace[-1], "host-agent")
            self.assertIn(lesson["id"], result["retrieval_influence"]["prior_lesson_ids"])
            self.assertEqual(result["retrieval_influence"]["parameter_mutation"], "none; approved parameters remain exact")
            self.assertEqual(result["result"]["container"], payload["params"]["container"])
            authorizations = [event for event in broker_module.audit.read(100) if event["type"] == "tool.authorized"]
            self.assertIn(lesson["id"], authorizations[-1]["payload"]["retrieval_influence"]["prior_lesson_ids"])


if __name__ == "__main__":
    unittest.main()
