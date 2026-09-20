"""Validated runtime bridge for MICA feature modules."""

from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from typing import Any


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _organization(action: str, payload: dict) -> Any:
    payload = payload if isinstance(payload, dict) else {}
    from core.organization import TaskPriority, TaskStatus, get_organization_manager
    manager = get_organization_manager()
    if action == "create_task":
        return {"task_id": manager.create_task(
            payload["title"], payload.get("description", ""),
            TaskPriority[payload.get("priority", "MEDIUM").upper()],
            payload.get("due_date"), float(payload.get("estimated_hours", 1.0)),
            payload.get("tags", []),
        )}
    if action == "list_tasks":
        status, priority = payload.get("status"), payload.get("priority")
        return manager.get_tasks(
            TaskStatus(status) if status else None,
            TaskPriority[priority.upper()] if priority else None,
            payload.get("tag"),
        )
    if action == "complete_task":
        return {"success": manager.complete_task(payload["task_id"])}
    if action == "create_event":
        return {"event_id": manager.create_event(
            payload["title"], payload.get("description", ""),
            payload["start_time"], payload["end_time"], payload.get("location", ""),
            payload.get("attendees", []), int(payload.get("reminder_minutes", 15)),
        )}
    if action == "upcoming_events":
        return manager.get_upcoming_events(int(payload.get("hours", 24)))
    if action == "deadlines":
        return manager.get_upcoming_deadlines(int(payload.get("days", 7)))
    if action == "overview":
        return manager.get_overview()
    raise ValueError(f"Unsupported organization action: {action}")


def _learning(action: str, payload: dict) -> Any:
    payload = payload if isinstance(payload, dict) else {}
    from core.learning import Difficulty, Subject, get_learning_manager
    manager = get_learning_manager()
    subject = Subject(payload.get("subject", Subject.GENERAL.value))
    if action == "explain_homework":
        return manager.explain_homework(subject, payload["topic"], payload["question"])
    if action == "create_study_plan":
        return {"plan_id": manager.create_study_plan(
            subject, payload["topics"], payload["exam_date"],
            float(payload.get("hours_per_day", 2.0)),
        )}
    if action == "record_session":
        return {"session_id": manager.record_session(
            subject, payload["topic"], int(payload["duration_minutes"]),
            float(payload["score"]), payload.get("notes", ""),
        )}
    if action == "progress":
        return manager.get_progress_report(subject if "subject" in payload else None)
    if action == "create_quiz":
        return {"quiz_id": manager.create_quiz(
            subject, payload["topic"], Difficulty(payload.get("difficulty", "beginner")),
            int(payload.get("num_questions", 5)),
        )}
    if action == "answer_quiz":
        score, results = manager.answer_quiz(payload["quiz_id"], payload["answers"])
        return {"score": score, "results": results}
    if action == "analyze_error":
        return manager.analyze_error(subject, payload["problem"], payload["solution_attempt"])
    if action == "explain_code":
        return manager.explain_code(payload["code"], payload.get("language", "python"))
    if action == "analyze_code_error":
        return manager.analyze_code_error(
            payload["code"], payload["error_message"], payload.get("language", "python")
        )
    if action == "summarize_document":
        return manager.summarize_document(payload["document_path"])
    if action == "search_pdf":
        return manager.search_pdf(payload["pdf_path"], payload["search_term"])
    if action == "search_knowledge":
        return manager.search_knowledge_base(payload["query"], payload.get("search_scope", "all"))
    if action == "overview":
        return manager.get_learning_overview()
    raise ValueError(f"Unsupported learning action: {action}")


def _automation(action: str, payload: dict) -> Any:
    from core.automation import (
        Action, ActionType, Priority, Trigger, TriggerType, get_automation_engine,
    )
    engine = get_automation_engine()
    payload = payload if isinstance(payload, dict) else {}
    if action == "list":
        return engine.list_automations(bool(payload.get("enabled_only", False)))
    if action == "run":
        return {"success": engine.run_automation(payload["automation_id"])}
    if action == "generate":
        return {"automation_id": engine.generate_automation_from_description(payload["description"])}
    if action == "create":
        actions = [Action(
            action_type=ActionType(item["action_type"]),
            parameters=item.get("parameters", {}), description=item.get("description", ""),
            timeout=int(item.get("timeout", 30)), retry_count=int(item.get("retry_count", 0)),
        ) for item in payload.get("actions", [])]
        if not actions:
            raise ValueError("At least one action is required")
        trigger = None
        if payload.get("trigger_type"):
            trigger = Trigger(
                trigger_type=TriggerType(payload["trigger_type"]),
                condition=str(payload.get("condition", "")),
                parameters=dict(payload.get("trigger_parameters", {})),
            )
        return {"automation_id": engine.create_automation(
            payload["name"], payload.get("description", ""), actions,
            trigger, Priority[payload.get("priority", "MEDIUM").upper()],
        )}
    if action == "create_if_then":
        actions = [Action(
            action_type=ActionType(item["action_type"]),
            parameters=item.get("parameters", {}), description=item.get("description", ""),
            timeout=int(item.get("timeout", 30)), retry_count=int(item.get("retry_count", 0)),
        ) for item in payload.get("actions", [])]
        if not actions:
            raise ValueError("At least one action is required")
        return {"automation_id": engine.create_if_then_rule(
            payload["condition"], actions, payload.get("name", "")
        )}
    if action == "chain":
        actions = [Action(
            action_type=ActionType(item["action_type"]),
            parameters=item.get("parameters", {}), description=item.get("description", ""),
            timeout=int(item.get("timeout", 30)), retry_count=int(item.get("retry_count", 0)),
        ) for item in payload.get("actions", [])]
        if not actions:
            raise ValueError("At least one action is required")
        return {"automation_id": engine.chain_actions(actions, payload.get("name", ""))}
    if action == "create_routine":
        return {"success": engine.create_routine(
            payload["name"], [str(item) for item in payload.get("automation_ids", [])],
            payload.get("description", ""),
        )}
    if action == "run_routine":
        return {"success": engine.run_routine(payload["name"])}
    if action == "prioritize":
        priorities = [Priority[str(item).upper()] for item in payload.get("priorities", [])]
        return {"success": engine.prioritize_tasks(
            [str(item) for item in payload.get("automation_ids", [])], priorities
        )}
    if action == "enable":
        return {"success": engine.enable_automation(payload["automation_id"])}
    if action == "disable":
        return {"success": engine.disable_automation(payload["automation_id"])}
    if action == "delete":
        return {"success": engine.delete_automation(payload["automation_id"])}
    if action == "status":
        return engine.get_automation_status(payload["automation_id"])
    if action == "schedule_recurring":
        actions = [Action(
            action_type=ActionType(item["action_type"]),
            parameters=item.get("parameters", {}), description=item.get("description", ""),
            timeout=int(item.get("timeout", 30)), retry_count=int(item.get("retry_count", 0)),
        ) for item in payload.get("actions", [])]
        if not actions:
            raise ValueError("At least one action is required")
        return {"automation_id": engine.schedule_recurring_task(
            payload["name"], actions, payload["time"], payload.get("frequency", "daily")
        )}
    raise ValueError(f"Unsupported automation action: {action}")


def _smart_home(action: str, payload: dict) -> Any:
    from core.smart_home import (
        Camera, ContactSensor, Light, MotionSensor, Sensor, Switch,
        Thermostat, get_smart_home_manager,
    )
    manager = get_smart_home_manager()
    if action == "register_device":
        kind, room = payload["device_type"], payload.get("room", "default")
        args = (payload["device_id"], payload["name"])
        factories = {
            "light": lambda: Light(*args, room),
            "switch": lambda: Switch(*args, room),
            "thermostat": lambda: Thermostat(*args, room),
            "sensor": lambda: Sensor(*args, payload.get("sensor_type", "generic"), room),
            "camera": lambda: Camera(*args, room, str(payload.get("stream_url", ""))),
            "motion_sensor": lambda: MotionSensor(*args, room),
            "door_sensor": lambda: ContactSensor(*args, room, "door"),
            "window_sensor": lambda: ContactSensor(*args, room, "window"),
        }
        if kind not in factories:
            raise ValueError(f"Unsupported device type: {kind}")
        return {"success": manager.add_device(factories[kind]())}
    if action == "control":
        return {"success": manager.control_device(
            payload["device_id"], payload["command"], **dict(payload.get("parameters", {}))
        )}
    if action == "create_scene":
        return {"success": manager.create_scene(payload["name"], payload["actions"])}
    if action == "execute_scene":
        return {"success": manager.execute_scene(payload["name"])}
    if action == "away":
        return {"success": manager.activate_away_mode() if payload.get("enabled", True) else manager.deactivate_away_mode()}
    if action == "status":
        return manager.get_status()
    if action == "devices":
        return manager.get_device_states()
    raise ValueError(f"Unsupported smart_home action: {action}")


def _intercom(action: str, payload: dict) -> Any:
    from core.intercom_mode import get_intercom_mode
    intercom = get_intercom_mode()
    if action == "activate":
        return {"success": intercom.activate(payload.get("room", "default"))}
    if action == "connect":
        return {"success": intercom.connect_to_room(payload["room"])}
    if action == "send":
        return {"success": intercom.send_message(payload["message"], payload.get("room"))}
    if action == "receive":
        return intercom.receive_message()
    if action == "status":
        return intercom.get_status()
    raise ValueError(f"Unsupported intercom action: {action}")


def _dashboard(action: str, payload: dict) -> Any:
    from core.personal_dashboard import get_personal_dashboard
    dashboard = get_personal_dashboard()
    if action == "refresh":
        return dashboard.refresh_dashboard_data()
    if action == "layout":
        return dashboard.get_dashboard_layout()
    raise ValueError(f"Unsupported dashboard action: {action}")


def _mica_3d(action: str, payload: dict) -> Any:
    from core.mica_3d import ObjectType, get_mica_3d_integration
    integration = get_mica_3d_integration()
    if action == "connect":
        return {"success": integration.connect(payload.get("connection_string", ""))}
    if action == "create_object":
        return {"object_id": integration.create_object(
            ObjectType(payload.get("object_type", "cube")), payload["name"],
            tuple(payload.get("position", (0, 0, 0))), tuple(payload.get("scale", (1, 1, 1))),
        )}
    if action == "list_objects":
        return integration.list_objects()
    if action == "save_scene":
        return {"success": integration.save_scene(payload["name"])}
    if action == "load_scene":
        return {"success": integration.load_scene(payload["name"])}
    if action == "status":
        return integration.get_scene_info()
    raise ValueError(f"Unsupported mica_3d action: {action}")


_autonomous_specs: dict[str, dict] = {}


def _execute_autonomous_task(task) -> dict:
    spec = _autonomous_specs.get(task.task_id)
    if not spec:
        return {"success": False, "output": "No structured target action was supplied"}
    if spec["domain"] == "autonomous":
        return {"success": False, "output": "Recursive autonomous execution is not allowed"}
    result = _dispatch(spec["domain"], spec["action"], spec.get("payload", {}))
    success = bool(result.get("success")) if isinstance(result, dict) and "success" in result else result is not None
    return {"success": success, "output": _jsonable(result)}


def _autonomous(action: str, payload: dict) -> Any:
    from core.autonomous_mode import AutonomyLevel, get_autonomous_mode
    mode = get_autonomous_mode()
    mode.set_task_executor(_execute_autonomous_task)
    if action == "activate":
        mode.activate(AutonomyLevel(payload.get("level", "semi_autonomous")))
        return {"success": True}
    if action == "add":
        task_id = mode.add_task(payload["description"])
        if payload.get("target_domain") and payload.get("target_action"):
            _autonomous_specs[task_id] = {
                "domain": payload["target_domain"], "action": payload["target_action"],
                "payload": payload.get("target_payload", {}),
            }
        return {"task_id": task_id}
    if action == "execute_next":
        return mode.execute_next_task()
    if action == "confirm":
        return {"success": mode.confirm_task(payload["task_id"], bool(payload["approved"]))}
    if action == "status":
        return mode.get_queue_status()
    raise ValueError(f"Unsupported autonomous action: {action}")


def _server(action: str, payload: dict) -> Any:
    from core.server_monitor import get_server_monitor
    monitor = get_server_monitor()
    if action == "status":
        return monitor.get_overall_status()
    if action == "alerts":
        return monitor.get_alerts()
    raise ValueError(f"Unsupported server action: {action}")


_HANDLERS = {
    "organization": _organization, "learning": _learning, "automation": _automation,
    "smart_home": _smart_home, "intercom": _intercom, "dashboard": _dashboard,
    "mica_3d": _mica_3d, "autonomous": _autonomous, "server": _server,
}


def _dispatch(domain: str, action: str, payload: dict) -> Any:
    handler = _HANDLERS.get(domain)
    if handler is None:
        raise ValueError(f"Unsupported feature domain: {domain}")
    return handler(action, payload)


def mica_feature(parameters: dict, response=None, player=None, session_memory=None) -> str:
    """Dispatch a feature action and return a JSON envelope."""
    parameters = parameters or {}
    domain = str(parameters.get("domain", "")).strip().lower()
    action = str(parameters.get("action", "")).strip().lower()
    payload = parameters.get("payload", {})
    if isinstance(payload, str):
        payload = json.loads(payload or "{}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    try:
        if not domain or not action:
            raise ValueError("domain and action are required")
        envelope = {"ok": True, "result": _jsonable(_dispatch(domain, action, payload))}
    except Exception as exc:
        envelope = {"ok": False, "error": str(exc)}
    return json.dumps(envelope, ensure_ascii=False, default=str)
