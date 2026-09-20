"""
Flexible Automatisierungs-Framework.
Implementiert Punkte 61-70: Automatisierung Funktionalität.
"""
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, time as time_type, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import sys

# Einfacher Scheduler als Alternative zum schedule Paket
class SimpleScheduler:
    """Einfacher Scheduler für zeitbasierte Automationen."""
    
    def __init__(self):
        self.tasks = []
        self.running = False
        self.thread = None
    
    def every(self):
        """Erstelle neue periodische Aufgabe."""
        return ScheduleJob(self)
    
    def run_pending(self):
        """Führe fällige Aufgaben aus."""
        now = datetime.now()
        for task in self.tasks:
            if task.should_run(now):
                task.run()
    
    def start(self):
        """Starte Scheduler."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
    
    def _run_loop(self):
        """Scheduler Loop."""
        while self.running:
            self.run_pending()
            time.sleep(1)
    
    def stop(self):
        """Stoppe Scheduler."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)


class ScheduleJob:
    """Einzelner geplanter Job."""
    
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.interval = None
        self.unit = None
        self.at_time = None
        self.job_func = None
        self.last_run = None
    
    def day(self):
        """Täglich."""
        self.unit = 'days'
        self.interval = 1
        return self
    
    def at(self, time_str):
        """Setze Zeit."""
        self.at_time = time_str
        return self
    
    def do(self, job_func, *args, **kwargs):
        """Setze Funktion."""
        self.job_func = lambda: job_func(*args, **kwargs)
        self.scheduler.tasks.append(self)
        return self
    
    def should_run(self, now):
        """Prüfe ob Job laufen sollte."""
        if not self.job_func:
            return False
        
        if self.unit == 'days' and self.at_time:
            target_time = datetime.strptime(self.at_time, "%H:%M").time()
            target_datetime = datetime.combine(now.date(), target_time)
            
            # Prüfe ob heute schon gelaufen
            if self.last_run and self.last_run.date() == now.date():
                return False
            
            # Prüfe ob Zeit erreicht
            if now >= target_datetime and (self.last_run is None or self.last_run < target_datetime):
                return True
        
        return False
    
    def run(self):
        """Führe Job aus."""
        if self.job_func:
            try:
                self.job_func()
                self.last_run = datetime.now()
            except Exception as e:
                print(f"[Scheduler] Job error: {e}")
    
    def cancel(self):
        """Cancel Job."""
        if self in self.scheduler.tasks:
            self.scheduler.tasks.remove(self)


# Nutze SimpleScheduler statt schedule
schedule = SimpleScheduler()


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
AUTOMATION_CONFIG_PATH = BASE_DIR / "config" / "automation.json"


class ActionType(Enum):
    """Aktions-Typen."""
    SYSTEM_COMMAND = "system_command"
    FUNCTION_CALL = "function_call"
    WEB_REQUEST = "web_request"
    FILE_OPERATION = "file_operation"
    SMART_HOME = "smart_home"
    CUSTOM = "custom"


class TriggerType(Enum):
    """Trigger-Typen."""
    TIME = "time"
    EVENT = "event"
    CONDITION = "condition"
    MANUAL = "manual"
    VOICE = "voice"


class Priority(Enum):
    """Prioritäts-Level."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Action:
    """Einzelne Aktion in einer Automation."""
    action_id: str = ""
    action_type: ActionType = ActionType.CUSTOM
    parameters: Dict[str, Any] = None
    description: str = ""
    timeout: int = 30
    retry_count: int = 0
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}
        if not self.action_id:
            self.action_id = f"action_{datetime.now().strftime('%Y%m%d%H%M%S')}"


@dataclass
class Trigger:
    """Trigger für Automation."""
    trigger_id: str = ""
    trigger_type: TriggerType = TriggerType.MANUAL
    condition: str = ""  # Bedingung als String
    parameters: Dict[str, Any] = None
    enabled: bool = True
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}
        if not self.trigger_id:
            self.trigger_id = f"trigger_{datetime.now().strftime('%Y%m%d%H%M%S')}"


@dataclass
class Automation:
    """Vollständige Automation."""
    automation_id: str = ""
    name: str = ""
    description: str = ""
    actions: List[Action] = None
    trigger: Optional[Trigger] = None
    priority: Priority = Priority.MEDIUM
    enabled: bool = True
    created_at: str = ""
    last_run: Optional[str] = None
    run_count: int = 0
    success_count: int = 0
    
    def __post_init__(self):
        if self.actions is None:
            self.actions = []
        if not self.automation_id:
            self.automation_id = f"auto_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class AutomationEngine:
    """Verwaltet und führt Automationen aus."""
    
    def __init__(self):
        self.automations: Dict[str, Automation] = {}
        self.routines: Dict[str, List[str]] = {}  # routine_name -> automation_ids
        self.scheduled_tasks: Dict[str, schedule.Job] = {}
        self.event_handlers: Dict[str, List[str]] = {}  # event_type -> automation_ids
        self.config = self._load_config()
        self.running = False
        self.scheduler_thread: Optional[threading.Thread] = None
        self.action_handlers: Dict[ActionType, Callable] = {}
        self._register_default_handlers()
    
    def _load_config(self) -> dict:
        """Lade Automatisierungs-Konfiguration."""
        default_config = {
            "max_retries": 3,
            "default_timeout": 30,
            "enable_logging": True,
            "log_path": str(BASE_DIR / "automation_logs")
        }
        
        try:
            if AUTOMATION_CONFIG_PATH.exists():
                loaded = json.loads(AUTOMATION_CONFIG_PATH.read_text(encoding="utf-8"))
                return {**default_config, **loaded}
        except Exception:
            pass
        
        return default_config
    
    def _save_config(self) -> None:
        """Speichere Automatisierungs-Konfiguration."""
        AUTOMATION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTOMATION_CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def _register_default_handlers(self) -> None:
        """Registriere Standard-Aktions-Handler."""
        self.action_handlers[ActionType.SYSTEM_COMMAND] = self._handle_system_command
        self.action_handlers[ActionType.FUNCTION_CALL] = self._handle_function_call
        self.action_handlers[ActionType.FILE_OPERATION] = self._handle_file_operation
        self.action_handlers[ActionType.SMART_HOME] = self._handle_smart_home
        self.action_handlers[ActionType.CUSTOM] = self._handle_custom
    
    def register_action_handler(self, action_type: ActionType, handler: Callable) -> None:
        """Registriere einen custom Handler."""
        self.action_handlers[action_type] = handler
    
    def create_automation(self, 
                         name: str, 
                         description: str, 
                         actions: List[Action],
                         trigger: Optional[Trigger] = None,
                         priority: Priority = Priority.MEDIUM) -> str:
        """
        Erstelle eine Automation (Punkt 61).
        
        Args:
            name: Name der Automation
            description: Beschreibung
            actions: Liste von Aktionen
            trigger: Optionaler Trigger
            priority: Priorität
            
        Returns:
            Automation ID
        """
        automation_id = f"auto_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        automation = Automation(
            automation_id=automation_id,
            name=name,
            description=description,
            actions=actions,
            trigger=trigger,
            priority=priority,
            enabled=True,
            created_at=datetime.now().isoformat()
        )
        
        self.automations[automation_id] = automation
        
        # Trigger registrieren
        if trigger and trigger.enabled:
            self._register_trigger(automation_id, trigger)
        
        return automation_id
    
    def _register_trigger(self, automation_id: str, trigger: Trigger) -> None:
        """Registriere Trigger für Automation."""
        if trigger.trigger_type == TriggerType.TIME:
            self._schedule_time_trigger(automation_id, trigger)
        elif trigger.trigger_type == TriggerType.EVENT:
            event_type = trigger.parameters.get("event_type", "default")
            if event_type not in self.event_handlers:
                self.event_handlers[event_type] = []
            self.event_handlers[event_type].append(automation_id)
    
    def _schedule_time_trigger(self, automation_id: str, trigger: Trigger) -> None:
        """Plane zeitbasierten Trigger (Punkt 63)."""
        try:
            time_str = trigger.parameters.get("time", "00:00")
            if time_str:
                job = schedule.every().day.at(time_str).do(
                    self.run_automation, automation_id
                )
                self.scheduled_tasks[automation_id] = job
        except Exception as e:
            print(f"[Automation] Error scheduling trigger: {e}")
    
    def start_automation_by_voice(self, automation_name: str) -> bool:
        """
        Starte Automation per Sprache (Punkt 62).
        
        Args:
            automation_name: Name der Automation
            
        Returns:
            True wenn erfolgreich gestartet
        """
        # Suche Automation nach Name
        for auto_id, automation in self.automations.items():
            if automation.name.lower() == automation_name.lower() and automation.enabled:
                return self.run_automation(auto_id)
        return False
    
    def run_automation(self, automation_id: str) -> bool:
        """
        Führe Automation aus.
        
        Args:
            automation_id: ID der Automation
            
        Returns:
            True wenn erfolgreich
        """
        automation = self.automations.get(automation_id)
        if not automation or not automation.enabled:
            return False
        
        automation.last_run = datetime.now().isoformat()
        automation.run_count += 1
        
        try:
            # Aktionen priorisiert ausführen
            sorted_actions = sorted(automation.actions, key=lambda a: a.timeout)
            
            for action in sorted_actions:
                success = self._execute_action(action)
                if not success and action.retry_count > 0:
                    # Retry Logic
                    for attempt in range(action.retry_count):
                        success = self._execute_action(action)
                        if success:
                            break
            
            automation.success_count += 1
            return True
            
        except Exception as e:
            print(f"[Automation] Error executing {automation_id}: {e}")
            return False
    
    def _execute_action(self, action: Action) -> bool:
        """Führe einzelne Aktion aus."""
        handler = self.action_handlers.get(action.action_type)
        if handler:
            try:
                return handler(action)
            except Exception as e:
                print(f"[Automation] Action error: {e}")
                return False
        return False
    
    def _handle_system_command(self, action: Action) -> bool:
        """Handle System Command Aktion."""
        import subprocess
        command = action.parameters.get("command", "")
        if not command:
            return False
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=action.timeout
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _handle_function_call(self, action: Action) -> bool:
        """Handle Function Call Aktion."""
        function_name = action.parameters.get("function", "")
        args = action.parameters.get("args", [])
        kwargs = action.parameters.get("kwargs", {})
        
        # Hier könnte man Funktionen aus einem Registry aufrufen
        # Für jetzt placeholder
        print(f"[Automation] Would call function: {function_name}")
        return True
    
    def _handle_file_operation(self, action: Action) -> bool:
        """Handle File Operation Aktion."""
        operation = action.parameters.get("operation", "")
        file_path = action.parameters.get("path", "")
        
        try:
            if operation == "create":
                Path(file_path).parent.mkdir(parents=True, exist_ok=True)
                Path(file_path).write_text(action.parameters.get("content", ""))
                return True
            elif operation == "delete":
                Path(file_path).unlink()
                return True
            elif operation == "copy":
                import shutil
                shutil.copy(file_path, action.parameters.get("destination"))
                return True
            elif operation == "move":
                import shutil
                shutil.move(file_path, action.parameters.get("destination"))
                return True
        except Exception as e:
            print(f"[Automation] File operation error: {e}")
            return False
        
        return False
    
    def _handle_smart_home(self, action: Action) -> bool:
        """Handle Smart Home Aktion."""
        try:
            from core.smart_home import get_smart_home_manager
            shm = get_smart_home_manager()
            
            device_id = action.parameters.get("device_id")
            action_name = action.parameters.get("action")
            params = action.parameters.get("params", {})
            
            return shm.control_device(device_id, action_name, **params)
        except Exception as e:
            print(f"[Automation] Smart home error: {e}")
            return False
    
    def _handle_custom(self, action: Action) -> bool:
        """Handle Custom Aktion."""
        # Placeholder für custom actions
        print(f"[Automation] Custom action: {action.description}")
        return True
    
    def trigger_event(self, event_type: str, event_data: Dict = None) -> List[str]:
        """
        Trigger ein Ereignis (Punkt 64).
        
        Args:
            event_type: Typ des Ereignisses
            event_data: Zusätzliche Daten
            
        Returns:
            Liste der ausgeführten Automation IDs
        """
        triggered_automations = []
        
        if event_type in self.event_handlers:
            for automation_id in self.event_handlers[event_type]:
                automation = self.automations.get(automation_id)
                if automation and automation.enabled:
                    success = self.run_automation(automation_id)
                    if success:
                        triggered_automations.append(automation_id)
        
        return triggered_automations
    
    def create_if_then_rule(self, 
                           condition: str, 
                           then_actions: List[Action],
                           rule_name: str = "") -> str:
        """
        Erstelle Wenn-Dann-Regel (Punkt 65).
        
        Args:
            condition: Bedingung als String
            then_actions: Aktionen die bei Erfüllung ausgeführt werden
            rule_name: Optionaler Name
            
        Returns:
            Regel ID
        """
        trigger = Trigger(
            trigger_id=f"trigger_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            trigger_type=TriggerType.CONDITION,
            condition=condition,
            parameters={"condition": condition},
            enabled=True
        )
        
        return self.create_automation(
            name=rule_name or f"Rule: {condition}",
            description=f"If-Then rule: {condition}",
            actions=then_actions,
            trigger=trigger,
            priority=Priority.MEDIUM
        )
    
    def chain_actions(self, actions: List[Action], chain_name: str = "") -> str:
        """
        Verkette mehrere Aktionen (Punkt 66).
        
        Args:
            actions: Liste von Aktionen
            chain_name: Optionaler Name
            
        Returns:
            Chain ID
        """
        return self.create_automation(
            name=chain_name or "Action Chain",
            description="Chained actions",
            actions=actions,
            trigger=None,  # Manuel ausgelöst
            priority=Priority.MEDIUM
        )
    
    def create_routine(self, 
                      routine_name: str, 
                      automation_ids: List[str],
                      description: str = "") -> bool:
        """
        Erstelle Routine aus mehreren Automationen (Punkt 67).
        
        Args:
            routine_name: Name der Routine
            automation_ids: Liste der Automation IDs
            description: Beschreibung
            
        Returns:
            True wenn erfolgreich
        """
        # Prüfe ob alle Automationen existieren
        for auto_id in automation_ids:
            if auto_id not in self.automations:
                return False
        
        self.routines[routine_name] = automation_ids
        return True
    
    def run_routine(self, routine_name: str) -> bool:
        """
        Führe Routine aus.
        
        Args:
            routine_name: Name der Routine
            
        Returns:
            True wenn erfolgreich
        """
        if routine_name not in self.routines:
            return False
        
        success_count = 0
        for automation_id in self.routines[routine_name]:
            if self.run_automation(automation_id):
                success_count += 1
        
        return success_count > 0
    
    def schedule_recurring_task(self, 
                               task_name: str,
                               actions: List[Action],
                               schedule_time: str,
                               frequency: str = "daily") -> str:
        """
        Plane wiederkehrende Aufgabe (Punkt 68).
        
        Args:
            task_name: Name der Aufgabe
            actions: Aktionen
            schedule_time: Zeit als "HH:MM"
            frequency: "daily", "weekly", "monthly"
            
        Returns:
            Task ID
        """
        trigger = Trigger(
            trigger_id=f"trigger_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            trigger_type=TriggerType.TIME,
            condition="",
            parameters={
                "time": schedule_time,
                "frequency": frequency
            },
            enabled=True
        )
        
        return self.create_automation(
            name=task_name,
            description=f"Recurring task: {frequency} at {schedule_time}",
            actions=actions,
            trigger=trigger,
            priority=Priority.MEDIUM
        )
    
    def prioritize_tasks(self, task_ids: List[str], priorities: List[Priority]) -> bool:
        """
        Priorisiere Aufgaben (Punkt 69).
        
        Args:
            task_ids: Liste der Task IDs
            priorities: Liste der Prioritäten
            
        Returns:
            True wenn erfolgreich
        """
        if len(task_ids) != len(priorities):
            return False
        
        for task_id, priority in zip(task_ids, priorities):
            if task_id in self.automations:
                self.automations[task_id].priority = priority
        
        return True
    
    def generate_automation_from_description(self, description: str) -> Optional[str]:
        """
        Generiere Automation aus natürlicher Sprache (Punkt 70).
        
        Args:
            description: Beschreibung in natürlicher Sprache
            
        Returns:
            Automation ID oder None
        """
        # Einfache Schlüsselwort-basierte Generierung
        # Echte Implementierung würde NLP/LLM benötigen
        
        actions = []
        
        # Schlüsselwort-Erkennung
        if "file" in description.lower() and "delete" in description.lower():
            actions.append(Action(
                action_id="action_1",
                action_type=ActionType.FILE_OPERATION,
                parameters={
                    "operation": "delete",
                    "path": description.lower().split("delete")[-1].strip()
                },
                description="Delete file"
            ))
        
        elif "backup" in description.lower():
            actions.append(Action(
                action_id="action_1",
                action_type=ActionType.SYSTEM_COMMAND,
                parameters={
                    "command": "echo 'Backup would run here'"
                },
                description="Run backup"
            ))
        
        elif "smart home" in description.lower() or "light" in description.lower():
            actions.append(Action(
                action_id="action_1",
                action_type=ActionType.SMART_HOME,
                parameters={
                    "device_id": "light1",
                    "action": "turn_on"
                },
                description="Control smart home"
            ))
        
        if not actions:
            return None
        
        return self.create_automation(
            name=f"Generated: {description[:30]}",
            description=description,
            actions=actions,
            trigger=None,
            priority=Priority.MEDIUM
        )
    
    def get_automation_status(self, automation_id: str) -> Optional[dict]:
        """Gib Status einer Automation zurück."""
        automation = self.automations.get(automation_id)
        if not automation:
            return None
        
        return {
            "automation_id": automation.automation_id,
            "name": automation.name,
            "enabled": automation.enabled,
            "priority": automation.priority.value,
            "run_count": automation.run_count,
            "success_count": automation.success_count,
            "last_run": automation.last_run,
            "created_at": automation.created_at
        }
    
    def list_automations(self, enabled_only: bool = False) -> List[dict]:
        """Liste alle Automationen auf."""
        automations = []
        for automation in self.automations.values():
            if enabled_only and not automation.enabled:
                continue
            automations.append({
                "automation_id": automation.automation_id,
                "name": automation.name,
                "description": automation.description,
                "enabled": automation.enabled,
                "priority": automation.priority.value,
                "action_count": len(automation.actions)
            })
        return automations
    
    def enable_automation(self, automation_id: str) -> bool:
        """Aktiviere Automation."""
        if automation_id in self.automations:
            self.automations[automation_id].enabled = True
            return True
        return False
    
    def disable_automation(self, automation_id: str) -> bool:
        """Deaktiviere Automation."""
        if automation_id in self.automations:
            self.automations[automation_id].enabled = False
            return True
        return False
    
    def delete_automation(self, automation_id: str) -> bool:
        """Lösche Automation."""
        if automation_id in self.automations:
            del self.automations[automation_id]
            # Entferne aus scheduled tasks
            if automation_id in self.scheduled_tasks:
                self.scheduled_tasks[automation_id].cancel()
                del self.scheduled_tasks[automation_id]
            return True
        return False
    
    def start_scheduler(self) -> None:
        """Starte den Scheduler für zeitbasierte Automationen."""
        if not self.running:
            self.running = True
            schedule.start()
    
    def stop_scheduler(self) -> None:
        """Stoppe den Scheduler."""
        if self.running:
            self.running = False
            schedule.stop()


# Globale Instanz für einfache Nutzung
_automation_engine = None

def get_automation_engine() -> AutomationEngine:
    """Gibt die globale AutomationEngine Instanz zurück."""
    global _automation_engine
    if _automation_engine is None:
        _automation_engine = AutomationEngine()
        _automation_engine.start_scheduler()
    return _automation_engine