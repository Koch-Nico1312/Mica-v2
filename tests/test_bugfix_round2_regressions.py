"""Regressions for the second bugfix round (review of 2026-09-20, fixes verified)."""

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from actions.mica_features import mica_feature
from core.automation import Action, ActionType, AutomationEngine, Trigger, TriggerType
from core.autonomous_mode import AutonomousMode, AutonomyLevel, TaskComplexity
from core.autonomous_server_agent import AutonomousServerAgent, Issue, Severity
from core.learning import Difficulty, LearningManager, Subject
from core.mica_3d import Mica3DIntegration, ObjectType
from core.organization import OrganizationManager
from core.smart_home import (
    Camera,
    ContactSensor,
    InMemorySmartHomeAdapter,
    Light,
    MotionSensor,
    SmartHomeManager,
    get_motion_gate,
)


@pytest.fixture(autouse=True)
def _fresh_smart_home_singletons():
    with patch("core.smart_home._smart_home_manager", None), patch(
        "core.smart_home._motion_gate", None
    ):
        yield


def test_automation_preserves_action_chain_order():
    engine = AutomationEngine()
    slow = Action(action_type=ActionType.CUSTOM, description="slow", timeout=120)
    fast = Action(action_type=ActionType.CUSTOM, description="fast", timeout=1)
    automation_id = engine.create_automation("chain", "", [slow, fast])
    stored = engine.automations[automation_id].actions
    assert [action.description for action in stored] == ["slow", "fast"]


def test_file_delete_requires_explicit_confirm():
    engine = AutomationEngine()
    with tempfile.TemporaryDirectory() as tmp:
        victim = Path(tmp) / "victim.txt"
        victim.write_text("x", encoding="utf-8")

        without_confirm = Action(
            action_type=ActionType.FILE_OPERATION,
            parameters={"operation": "delete", "path": str(victim)},
        )
        automation_id = engine.create_automation("delete-no-confirm", "", [without_confirm])
        assert engine.run_automation(automation_id) is False
        assert victim.exists()

        with_confirm = Action(
            action_type=ActionType.FILE_OPERATION,
            parameters={"operation": "delete", "path": str(victim), "confirm": True},
        )
        automation_id = engine.create_automation("delete-confirm", "", [with_confirm])
        assert engine.run_automation(automation_id) is True
        assert not victim.exists()


def test_generate_automation_only_targets_registered_devices():
    with tempfile.TemporaryDirectory() as tmp, patch(
        "core.smart_home.SMART_HOME_CONFIG_PATH", Path(tmp) / "smart_home.json"
    ):
        manager = SmartHomeManager(adapter=InMemorySmartHomeAdapter())
        manager.add_device(Light("light.living", "Wohnzimmerlampe"))

        engine = AutomationEngine()
        automation_id = engine.generate_automation_from_description("schalte Wohnzimmerlampe aus")
        assert automation_id is not None
        action = engine.automations[automation_id].actions[0]
        assert action.parameters["device_id"] == "light.living"
        assert action.parameters["action"] == "turn_off"

        # Ohne registriertes Licht darf nichts erfunden werden.
        with patch("core.smart_home._smart_home_manager", None):
            empty_config = Path(tmp) / "empty.json"
            empty_config.write_text("{}", encoding="utf-8")
            with patch("core.smart_home.SMART_HOME_CONFIG_PATH", empty_config):
                fresh = AutomationEngine()
                assert fresh.generate_automation_from_description("mach das licht an") is None
        # Destruktive Generierung bleibt blockiert.
        assert engine.generate_automation_from_description("loesche alle dateien") is None


def test_delete_automation_cleans_event_handlers():
    with tempfile.TemporaryDirectory() as tmp, patch(
        "core.automation.AUTOMATION_CONFIG_PATH", Path(tmp) / "automation.json"
    ):
        engine = AutomationEngine()
        automation_id = engine.create_automation(
            "ev", "", [], Trigger(trigger_type=TriggerType.EVENT, parameters={"event_type": "door_opened"})
        )
        assert engine.event_handlers["door_opened"] == [automation_id]
        assert engine.delete_automation(automation_id) is True
        assert "door_opened" not in engine.event_handlers


def test_if_then_rules_fire_through_registered_evaluator():
    with tempfile.TemporaryDirectory() as tmp, patch(
        "core.automation.AUTOMATION_CONFIG_PATH", Path(tmp) / "automation.json"
    ):
        _if_then_rules_fire_through_registered_evaluator(tmp)


def _if_then_rules_fire_through_registered_evaluator(tmp: str) -> None:
    engine = AutomationEngine()
    executed = []
    engine.register_action_handler(ActionType.CUSTOM, lambda action: executed.append(action.description) or True)
    engine.register_condition_evaluator(
        lambda condition, data: condition == "motion_detected"
        and bool((data or {}).get("motion"))
    )
    automation_id = engine.create_if_then_rule(
        "motion_detected",
        [Action(action_type=ActionType.CUSTOM, description="react")],
        "motion rule",
    )

    # Ohne Ereignis oder mit negativer Bedingung: keine Ausführung.
    assert engine.trigger_event("door_opened", None) == []
    assert engine.trigger_event("door_opened", {"motion": False}) == []

    assert engine.trigger_event("door_opened", {"motion": True}) == [automation_id]
    assert engine.automations[automation_id].run_count == 1
    assert executed == ["react"]


def test_autonomous_mode_quarantines_without_executor():
    mode = AutonomousMode()
    mode.activate(AutonomyLevel.FULLY_AUTONOMOUS)
    mode.add_task("open a file")
    result = mode.execute_next_task()
    assert result["success"] is False
    assert mode.task_queue == []
    assert mode.failed_tasks[0].results["terminal_reason"] == "no_executor"


def test_autonomous_retries_do_not_block_queue():
    attempts = {"count": 0}

    def flaky(task):
        attempts["count"] += 1
        return {"success": attempts["count"] >= 3, "output": f"try-{attempts['count']}"}

    mode = AutonomousMode(task_executor=flaky)
    mode.config.update({"auto_retry": True, "max_retries": 3})
    mode.activate(AutonomyLevel.FULLY_AUTONOMOUS)
    first = mode.add_task("flaky thing")
    second = mode.add_task("second thing")

    result = mode.execute_next_task()

    assert result["success"] is True
    assert attempts["count"] == 3
    assert [task.task_id for task in mode.task_queue] == [second]
    assert mode.get_task_status(first)["status"] == "completed"


def test_complexity_analysis_word_boundaries_and_german():
    mode = AutonomousMode()
    assert mode._analyze_task_complexity("formatiere die festplatte") == TaskComplexity.CRITICAL
    assert mode._analyze_task_complexity("loesche die datei") == TaskComplexity.CRITICAL
    assert mode._analyze_task_complexity("entferne die datei") == TaskComplexity.CRITICAL
    assert mode._analyze_task_complexity("entferne die erinnerung") != TaskComplexity.CRITICAL
    assert mode._analyze_task_complexity("mehr information anzeigen") == TaskComplexity.MODERATE


def test_service_restart_uses_target_not_description():
    agent = AutonomousServerAgent()
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)

        class Result:
            returncode = 0

        return Result()

    with patch.object(subprocess, "run", fake_run):
        ok = agent._fix_service(
            Issue(
                category="service_down",
                description="Service nginx is not active",
                target="nginx",
                severity=Severity.ERROR,
            )
        )
    assert ok is True
    assert commands == [["systemctl", "restart", "nginx"]]

    with patch.object(subprocess, "run", fake_run):
        refused = agent._fix_service(
            Issue(category="service_down", description="Service nginx is not active")
        )
    assert refused is False
    assert len(commands) == 1  # kein Restart-Versuch ohne valides Ziel


def test_motion_and_contact_devices_register_trigger_and_persist():
    with tempfile.TemporaryDirectory() as tmp, patch(
        "core.smart_home.SMART_HOME_CONFIG_PATH", Path(tmp) / "smart_home.json"
    ):
        events = []
        get_motion_gate().register(lambda device_id, event, sensor: events.append((device_id, event)))

        manager = SmartHomeManager(adapter=InMemorySmartHomeAdapter())
        manager.add_device(Camera("cam.out", "Door cam", "entry", "rtsp://x"))
        manager.add_device(MotionSensor("motion.hall", "Hall motion"))
        manager.add_device(ContactSensor("door.front", "Front door", "entry", "door"))

        manager.devices["motion.hall"].trigger_motion()
        manager.devices["door.front"].set_open(True)
        assert ("motion.hall", "triggered") in events
        assert ("door.front", "triggered") in events

        status = manager.get_status()["devices_by_type"]
        assert status["camera"] == 1
        assert status["motion_sensor"] == 1
        assert status["door_sensor"] == 1

        manager._persist_state()
        restored = SmartHomeManager(adapter=InMemorySmartHomeAdapter())
        assert isinstance(restored.devices["cam.out"], Camera)
        assert isinstance(restored.devices["motion.hall"], MotionSensor)
        assert isinstance(restored.devices["door.front"], ContactSensor)
        assert restored.devices["door.front"].open_state is True
        assert restored.devices["door.front"].device_type.value == "door_sensor"


def test_quiz_answers_are_scored_deterministically():
    with tempfile.TemporaryDirectory() as tmp, patch(
        "core.learning.LEARNING_DATA_PATH", Path(tmp) / "learning.json"
    ):
        manager = LearningManager()
        quiz_id = manager.create_quiz(Subject.MATHEMATICS, "Algebra", Difficulty.BEGINNER, 2)
        questions = manager.run_quiz(quiz_id)
        assert questions

        all_correct = {q.question_id: q.answer for q in questions}
        score, results = manager.answer_quiz(quiz_id, all_correct)
        assert score == 1.0
        assert all(item["correct"] for item in results)

        score_wrong, _ = manager.answer_quiz(quiz_id, {key: "sicher falsch" for key in all_correct})
        assert score_wrong == 0.0

        restored = LearningManager()
        assert quiz_id in restored.quizzes


def test_organization_tolerates_corrupt_timestamps():
    with tempfile.TemporaryDirectory() as tmp, patch(
        "core.organization.ORGANIZATION_DATA_PATH", Path(tmp) / "org.json"
    ):
        manager = OrganizationManager()
        manager.create_event("Gut", "", "2026-09-21T10:00:00", "2026-09-21T11:00:00")
        manager.create_event("Kaputt", "", "not-a-date", "also-bad")

        events = manager.read_calendar("2026-09-01", "2026-09-30")
        assert [event.title for event in events] == ["Gut"]
        assert manager.create_daily_plan("2026-09-21")["total_events"] == 1
        assert manager.check_overdue_deadlines() == []


def test_mica_3d_rejects_corrupt_scene_and_resets(tmp_path):
    scenes = tmp_path / "mica_3d_scenes"
    scenes.mkdir()
    (scenes / "bad.json").write_text(
        json.dumps({
            "objects": {},
            "cameras": {"c": "not-a-dict"},
        }),
        encoding="utf-8",
    )
    with patch("core.mica_3d.BASE_DIR", tmp_path):
        integration = Mica3DIntegration()
        integration.create_object(ObjectType.CUBE, "Cube")
        assert integration.save_scene("good") is True
        assert integration.load_scene("good") is True
        assert integration.scene_objects
        assert integration.load_scene("bad") is False
        assert integration.cameras == {}


def test_bridge_covers_new_domains_and_tolerates_missing_payload():
    with tempfile.TemporaryDirectory() as tmp, patch(
        "core.organization.ORGANIZATION_DATA_PATH", Path(tmp) / "org.json"
    ):
        listing = json.loads(mica_feature({"domain": "organization", "action": "list_tasks"}))
        assert listing["ok"] is True

    chain = json.loads(mica_feature({
        "domain": "automation", "action": "chain",
        "payload": json.dumps({
            "name": "chain",
            "actions": [{"action_type": "custom", "parameters": {}}],
        }),
    }))
    assert chain["ok"] is True and chain["result"]["automation_id"]

    motion = json.loads(mica_feature({
        "domain": "smart_home", "action": "register_device",
        "payload": json.dumps({"device_id": "motion.x", "name": "X", "device_type": "motion_sensor"}),
    }))
    assert motion["ok"] is True

    quiz = json.loads(mica_feature({
        "domain": "learning", "action": "create_quiz",
        "payload": json.dumps({"topic": "Algebra"}),
    }))
    assert quiz["ok"] is True
