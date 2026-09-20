"""Regression coverage for the 14 findings from the 2026-09-20 review."""

import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from actions.web_search import web_search
from actions.mica_features import mica_feature
from core.automation import (
    Action,
    ActionType,
    AutomationEngine,
    Priority,
    SimpleScheduler,
    Trigger,
    TriggerType,
)
from core.autonomous_mode import AutonomousMode, AutonomyLevel
from core.intercom_mode import IntercomMode
from core.learning import LearningManager, Subject
from core.mica_3d import Mica3DIntegration, ObjectType
from core.organization import OrganizationManager
from core.smart_home import InMemorySmartHomeAdapter, Light, SmartHomeManager
from core.whisper_mode import WhisperMode


class PersistenceRegressionTests(unittest.TestCase):
    def test_organization_round_trip_and_unique_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "organization.json"
            with patch("core.organization.ORGANIZATION_DATA_PATH", path):
                first = OrganizationManager()
                ids = [first.create_task(f"Task {index}", "") for index in range(3)]
                self.assertEqual(3, len(set(ids)))
                second = OrganizationManager()
                self.assertEqual(set(ids), set(second.tasks))

    def test_learning_round_trip_and_unique_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learning.json"
            with patch("core.learning.LEARNING_DATA_PATH", path):
                first = LearningManager()
                ids = [first.record_session(Subject.MATHEMATICS, "Algebra", 30, 0.8) for _ in range(3)]
                self.assertEqual(3, len(set(ids)))
                second = LearningManager()
                self.assertEqual(set(ids), set(second.sessions))
                self.assertTrue(second.progress)


class AutomationRegressionTests(unittest.TestCase):
    def test_failed_action_keeps_automation_failed(self):
        engine = AutomationEngine()
        action = Action(action_type=ActionType.FILE_OPERATION, parameters={
            "operation": "delete", "path": "definitely-does-not-exist"
        })
        automation_id = engine.create_automation("failure", "", [action])
        self.assertFalse(engine.run_automation(automation_id))
        self.assertEqual(0, engine.automations[automation_id].success_count)

    def test_frequency_selects_matching_scheduler_unit(self):
        engine = AutomationEngine()
        for frequency, expected in (("daily", "days"), ("weekly", "weeks"), ("monthly", "months")):
            trigger = Trigger(trigger_type=TriggerType.TIME, parameters={
                "time": "12:00", "frequency": frequency
            })
            automation_id = engine.create_automation(frequency, "", [], trigger)
            self.assertEqual(expected, engine.scheduled_tasks[automation_id].unit)

    def test_persistence_restores_enums_and_event_trigger(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "automation.json"
            output_path = Path(tmp) / "event.txt"
            scheduler = SimpleScheduler()
            with patch("core.automation.AUTOMATION_CONFIG_PATH", config_path), patch(
                "core.automation.schedule", scheduler
            ):
                first = AutomationEngine()
                automation_id = first.create_automation(
                    "event persistence",
                    "",
                    [Action(
                        action_type=ActionType.FILE_OPERATION,
                        parameters={"operation": "create", "path": str(output_path)},
                    )],
                    Trigger(
                        trigger_type=TriggerType.EVENT,
                        parameters={"event_type": "door_opened"},
                    ),
                    Priority.HIGH,
                )

                persisted = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual("file_operation", persisted["automations"][automation_id]["actions"][0]["action_type"])
                self.assertEqual("event", persisted["automations"][automation_id]["trigger"]["trigger_type"])

                restored = AutomationEngine()
                automation = restored.automations[automation_id]
                self.assertIs(ActionType.FILE_OPERATION, automation.actions[0].action_type)
                self.assertIs(TriggerType.EVENT, automation.trigger.trigger_type)
                self.assertIs(Priority.HIGH, automation.priority)
                self.assertIn(automation_id, restored.event_handlers["door_opened"])
                self.assertEqual([automation_id], restored.trigger_event("door_opened"))
                self.assertTrue(output_path.exists())

    def test_restart_restores_weekly_and_monthly_schedule_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "automation.json"
            scheduler = SimpleScheduler()
            with patch("core.automation.AUTOMATION_CONFIG_PATH", config_path), patch(
                "core.automation.schedule", scheduler
            ):
                first = AutomationEngine()
                weekly_id = first.schedule_recurring_task("weekly", [], "08:00", "weekly")
                monthly_id = first.schedule_recurring_task("monthly", [], "08:00", "monthly")
                first.automations[weekly_id].created_at = "2026-08-31T07:00:00"
                first.automations[weekly_id].last_run = "2026-09-07T08:00:00"
                first.automations[monthly_id].created_at = "2026-07-31T07:00:00"
                first.automations[monthly_id].last_run = "2026-08-31T08:00:00"
                first._save_automations()

                scheduler.tasks.clear()
                restored = AutomationEngine()
                weekly = restored.scheduled_tasks[weekly_id]
                monthly = restored.scheduled_tasks[monthly_id]

                self.assertEqual(datetime(2026, 8, 31, 7), weekly.created_at)
                self.assertEqual(datetime(2026, 9, 7, 8), weekly.last_run)
                self.assertFalse(weekly.should_run(datetime(2026, 9, 8, 9)))
                self.assertTrue(weekly.should_run(datetime(2026, 9, 14, 9)))
                self.assertEqual(datetime(2026, 7, 31, 7), monthly.created_at)
                self.assertEqual(datetime(2026, 8, 31, 8), monthly.last_run)
                self.assertFalse(monthly.should_run(datetime(2026, 9, 30, 9)))
                self.assertTrue(monthly.should_run(datetime(2026, 10, 31, 9)))


class ExecutionRegressionTests(unittest.TestCase):
    def test_autonomous_mode_fails_without_executor(self):
        mode = AutonomousMode()
        mode.activate(AutonomyLevel.FULLY_AUTONOMOUS)
        mode.add_task("open a file")
        result = mode.execute_next_task()
        self.assertFalse(result["success"])
        self.assertIn("executor", result["error"].lower())

    def test_autonomous_mode_reports_real_executor_result(self):
        calls = []
        mode = AutonomousMode(task_executor=lambda task: calls.append(task.description) or {"success": True, "output": "done"})
        mode.activate(AutonomyLevel.FULLY_AUTONOMOUS)
        mode.add_task("open a file")
        result = mode.execute_next_task()
        self.assertTrue(result["success"])
        self.assertEqual(["open a file"], calls)

    def test_autonomous_mode_quarantines_task_after_retry_limit(self):
        attempts = []

        def fail(task):
            attempts.append(task.task_id)
            return {"success": False, "output": f"failure-{len(attempts)}"}

        mode = AutonomousMode(task_executor=fail)
        mode.config.update({"auto_retry": True, "max_retries": 2})
        mode.activate(AutonomyLevel.FULLY_AUTONOMOUS)
        task_id = mode.add_task("open a file")

        for _ in range(3):
            mode.execute_next_task()

        self.assertEqual(3, len(attempts))
        self.assertEqual([], mode.task_queue)
        self.assertEqual([task_id], [task.task_id for task in mode.failed_tasks])
        status = mode.get_task_status(task_id)
        self.assertEqual("failed", status["status"])
        self.assertEqual("max_retries_exhausted", status["results"]["terminal_reason"])
        self.assertEqual(2, status["results"]["retry_count"])
        self.assertEqual(3, len(status["results"]["attempt_history"]))
        self.assertIsNone(mode.execute_next_task())
        self.assertEqual(3, len(attempts))

    def test_autonomous_mode_quarantines_failure_when_retries_disabled(self):
        mode = AutonomousMode(task_executor=lambda task: {"success": False, "error": "boom"})
        mode.config["auto_retry"] = False
        mode.activate(AutonomyLevel.FULLY_AUTONOMOUS)
        task_id = mode.add_task("open a file")

        mode.execute_next_task()

        self.assertEqual([], mode.task_queue)
        status = mode.get_task_status(task_id)
        self.assertEqual("auto_retry_disabled", status["results"]["terminal_reason"])
        attempt = status["results"]["attempt_history"][0]
        self.assertEqual("boom", attempt["error"])
        self.assertEqual("boom", attempt["output"]["error"])

    def test_whisper_rms_normalizes_int16_without_overflow(self):
        mode = WhisperMode()
        rms = mode.calculate_rms(np.full(1600, 1000, dtype=np.int16))
        self.assertAlmostEqual(1000 / 32768, rms, places=5)

    def test_scene_with_enum_serializes_and_loads(self):
        with tempfile.TemporaryDirectory() as tmp, patch("core.mica_3d.BASE_DIR", Path(tmp)):
            first = Mica3DIntegration()
            object_id = first.create_object(ObjectType.CUBE, "Cube")
            self.assertTrue(first.save_scene("test"))
            second = Mica3DIntegration()
            self.assertTrue(second.load_scene("test"))
            self.assertEqual(ObjectType.CUBE, second.scene_objects[object_id].object_type)

    def test_pdf_search_uses_extracted_text_and_does_not_invent_matches(self):
        class Page:
            def __init__(self, text):
                self.text = text
            def extract_text(self):
                return self.text
        fake_module = types.SimpleNamespace(PdfReader=lambda _: types.SimpleNamespace(
            pages=[Page("Alpha\nNeedle here"), Page("Nothing")]
        ))
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "sample.pdf"
            pdf.write_bytes(b"%PDF-fake")
            with patch.dict(sys.modules, {"pypdf": fake_module}):
                manager = LearningManager()
                self.assertEqual(1, len(manager.search_pdf(str(pdf), "needle")))
                self.assertEqual([], manager.search_pdf(str(pdf), "missing"))


class AdapterRegressionTests(unittest.TestCase):
    def test_runtime_feature_bridge_executes_organization_action(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "core.organization.ORGANIZATION_DATA_PATH", Path(tmp) / "organization.json"
        ):
            manager = OrganizationManager()
            with patch("core.organization.get_organization_manager", return_value=manager):
                created = json.loads(mica_feature({
                    "domain": "organization", "action": "create_task",
                    "payload": json.dumps({"title": "Bridge task"}),
                }))
                listed = json.loads(mica_feature({
                    "domain": "organization", "action": "list_tasks", "payload": "{}",
                }))
        self.assertTrue(created["ok"])
        self.assertEqual("Bridge task", listed["result"][0]["title"])

    def test_route_mode_does_not_require_query(self):
        with patch("actions.web_search.search_route", return_value="route-ok"):
            result = web_search({"mode": "route", "origin": "A", "destination": "B"})
        self.assertEqual("route-ok", result)

    def test_intercom_delivers_through_transport(self):
        delivered = []
        intercom = IntercomMode(transport=lambda room, payload: delivered.append(payload) or True)
        intercom.activate("office")
        intercom.config["rooms"]["kitchen"] = {
            "name": "Kitchen", "enabled": True, "endpoint": "https://room.invalid"
        }
        self.assertTrue(intercom.connect_to_room("kitchen"))
        self.assertTrue(intercom.send_message("hello", "kitchen"))
        self.assertEqual("hello", delivered[-1]["message"])

    def test_smart_home_fails_closed_without_adapter(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "core.smart_home.SMART_HOME_CONFIG_PATH", Path(tmp) / "smart-home.json"
        ):
            manager = SmartHomeManager()
            manager.add_device(Light("light.test", "Test"))
            self.assertFalse(manager.control_device("light.test", "turn_on"))

    def test_smart_home_updates_after_adapter_success_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "core.smart_home.SMART_HOME_CONFIG_PATH", Path(tmp) / "smart-home.json"
        ):
            manager = SmartHomeManager(adapter=InMemorySmartHomeAdapter())
            manager.add_device(Light("light.test", "Test"))
            self.assertTrue(manager.control_device("light.test", "turn_on"))
            restored = SmartHomeManager(adapter=InMemorySmartHomeAdapter())
            self.assertIn("light.test", restored.devices)


if __name__ == "__main__":
    unittest.main()
