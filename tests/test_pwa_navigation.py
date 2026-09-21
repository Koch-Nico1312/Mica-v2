from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class PwaNavigationTests(unittest.TestCase):
    def test_markdown_and_audit_are_mutually_navigable_without_duplicate_edges(self) -> None:
        document_id = "a" * 32
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "BRAIN_DIR": str(Path(temporary) / "brain"),
                "INDEX_PATH": str(Path(temporary) / "index.sqlite3"),
                "AUDIT_PATH": str(Path(temporary) / "audit.jsonl"),
                "APPROVAL_DB": str(Path(temporary) / "approvals.sqlite3"),
                "SCHEDULE_DB": str(Path(temporary) / "schedule.sqlite3"),
                "IMPROVEMENT_DB": str(Path(temporary) / "improvements.sqlite3"),
                "IMPROVEMENT_WORKSPACE": str(Path(temporary) / "improvements"),
                "CONNECTOR_DB": str(Path(temporary) / "connectors.sqlite3"),
                "MICA_APPROVAL_SECRET": "pwa-navigation-test",
            },
            clear=False,
        ):
            module = importlib.import_module("backend.services.api.app")
            module = importlib.reload(module)
            document = {
                "id": document_id,
                "kind": "lessons",
                "title": "Docker lesson",
                "created_at": "2026-09-06T10:00:00+00:00",
                "path": "/data/brain/lessons/test.md",
                "body": "Check the target container before retrying.",
            }
            event = {
                "hash": "b" * 64,
                "type": "task.failed",
                "timestamp": "2026-09-06T10:01:00+00:00",
                "payload": {
                    "brain_document": document_id,
                    "brain_references": [document_id],
                },
            }
            with (
                patch.object(module.brain, "documents", return_value=[document]),
                patch.object(module.brain, "graph", return_value={
                    "nodes": [{"id": document_id, "label": "Docker lesson", "kind": "lessons"}],
                    "links": [],
                }),
                patch.object(module.audit, "read", return_value=[event]),
                patch.object(module.audit, "verify", return_value=True),
            ):
                result = module.brain_explorer()

            self.assertEqual(result["graph"]["links"], [{
                "source": "audit:" + "b" * 16,
                "target": document_id,
            }])

        html = (ROOT / "backend" / "web_ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function openAudit(id)", html)
        self.assertIn("open:()=>openDocument(documentId)", html)
        self.assertIn("open:()=>openAudit(auditId(event))", html)
        self.assertIn("if(id.startsWith('audit:'))openAudit(id)", html)
        self.assertIn("item.onclick=()=>openAudit(auditId(event))", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
