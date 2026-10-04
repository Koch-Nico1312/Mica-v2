from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(ROOT))

from backend.backup_restore import BackupDrillError, create_backup, run_drill, verify_restore
from backend.preflight import check
from backend.services.common.audit import AuditLog
from backend.services.common.brain import MarkdownBrain


class BackupRestoreDrillTests(unittest.TestCase):
    def test_hindsight_pending_deletion_survives_backup_restore(self):
        from backend.services.common.hindsight import HindsightMemory
        from backend.backup_restore import _safe_extract, _rebuild_state_export
        import sqlite3
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            brain = MarkdownBrain(root / "data" / "brain", root / "data" / "index" / "brain.sqlite3")
            with patch.dict("os.environ", {"MICA_HINDSIGHT_DB": str(root / "data" / "memory-sync" / "hindsight.sqlite3")}):
                memory = HindsightMemory(brain)
                connection = memory._connect()
                try:
                    connection.execute("INSERT INTO sources VALUES (?,?,?)", (memory.scope, "a" * 32, "pending"))
                    connection.execute("INSERT INTO retries VALUES (?,?,?,?,?)", (memory.scope, "a" * 32, "deleted", 2, 9999999999))
                    connection.commit()
                finally:
                    connection.close()
            archive, _ = create_backup(root / "data", root / "backup")
            _safe_extract(archive, root / "restore")
            counts = _rebuild_state_export(root / "restore")
            self.assertEqual(counts["hindsight_sources"], 1)
            connection = sqlite3.connect(root / "restore" / "memory-sync" / "hindsight.sqlite3")
            try:
                self.assertEqual(connection.execute("SELECT id,fingerprint FROM sources").fetchone(), ("a" * 32, "pending"))
                self.assertEqual(connection.execute("SELECT target,attempts FROM retries").fetchone(), ("deleted", 2))
            finally:
                connection.close()
            self.assertTrue(verify_restore(archive)["passed"])

    def test_drill_preserves_truth_and_rebuilds_disposable_sqlite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "data"
            backup = root / "backup"
            brain = MarkdownBrain(data / "brain", data / "index" / "brain.sqlite3")
            brain.write("lessons", "Docker Fehler", "Unveränderte Docker-Ausgabe: container is missing")
            brain.write("tasks", "Wiederholung", "Vor dem Wiederholen Lesson lesen.")
            audit = AuditLog(data / "audit" / "events.jsonl")
            audit.append("task.failed", {"task_id": "test", "reason": "container is missing"})
            source_audit = audit.path.read_bytes()
            (data / "index" / "unrelated-cache.sqlite3").write_bytes(b"not backup truth")

            report = run_drill(data, backup)

            archive = Path(report["archive"])
            self.assertTrue(report["passed"])
            self.assertTrue(report["sqlite_rebuilt"])
            self.assertTrue(report["audit_valid"])
            self.assertEqual(audit.path.read_bytes(), source_audit)
            self.assertTrue(Path(report["report"]).is_file())
            with tarfile.open(archive, "r:gz") as bundle:
                names = bundle.getnames()
            self.assertTrue(any(name.startswith("brain/") for name in names))
            self.assertIn("audit/events.jsonl", names)
            self.assertNotIn("index/brain.sqlite3", names)
            self.assertNotIn("index/unrelated-cache.sqlite3", names)

    def test_corrupted_archive_is_refused_before_index_rebuild(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "data"
            brain = MarkdownBrain(data / "brain", data / "index" / "brain.sqlite3")
            brain.write("lessons", "Lesson", "Known-good evidence")
            archive, manifest = create_backup(data, root / "backup")
            changed = root / "changed.tar.gz"
            with tarfile.open(changed, "w:gz") as bundle:
                raw_manifest = json.dumps(manifest).encode("utf-8")
                info = tarfile.TarInfo("manifest.json")
                info.size = len(raw_manifest)
                bundle.addfile(info, io.BytesIO(raw_manifest))
                altered = b"tampered Markdown source"
                info = tarfile.TarInfo(manifest["files"][0]["path"])
                info.size = len(altered)
                bundle.addfile(info, io.BytesIO(altered))
            with self.assertRaises(BackupDrillError):
                verify_restore(changed)
            self.assertTrue(archive.is_file())

    def test_explicit_preflight_backup_drill_reports_restore_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "data"
            MarkdownBrain(data / "brain", data / "index" / "brain.sqlite3").write("tasks", "Preflight", "restore this")
            AuditLog(data / "audit" / "events.jsonl").append("task.planned", {"task_id": "preflight"})
            # Docker/GPU are independent preflight probes; isolate this test to
            # the explicit backup integration rather than running Docker here.
            with patch("backend.preflight._command", return_value=(True, "test")):
                report = check(data, [], backup_dir=root / "backup", backup_drill=True)
            self.assertTrue(report["backup"]["target_exists"])
            self.assertTrue(report["backup"]["drill_requested"])
            self.assertTrue(report["backup"]["drill_passed"])
            self.assertTrue(report["backup"]["detail"]["sqlite_rebuilt"])


if __name__ == "__main__":
    unittest.main()
