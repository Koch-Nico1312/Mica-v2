"""
"Mach es einfach"-Modus für autonome Aufgabenausführung.
Implementiert Punkt 100: "Mach es einfach"-Modus.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import sys

from core.ids import new_id


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
AUTONOMOUS_MODE_CONFIG_PATH = BASE_DIR / "config" / "autonomous_mode.json"


class AutonomyLevel(Enum):
    """Autonomie-Level."""
    FULLY_AUTONOMOUS = "fully_autonomous"
    SEMI_AUTONOMOUS = "semi_autonomous"
    CONFIRMATION_REQUIRED = "confirmation_required"
    MANUAL = "manual"


class TaskComplexity(Enum):
    """Aufgaben-Komplexität."""
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    CRITICAL = "critical"


@dataclass
class AutonomousTask:
    """Autonome Aufgabe."""
    task_id: str = ""
    description: str = ""
    complexity: TaskComplexity = TaskComplexity.MODERATE
    steps: List[str] = None
    required_tools: List[str] = None
    requires_confirmation: bool = False
    estimated_duration: int = 15  # minutes
    status: str = "pending"
    current_step: int = 0
    results: Dict = None
    
    def __post_init__(self):
        if self.steps is None:
            self.steps = []
        if self.required_tools is None:
            self.required_tools = []
        if self.results is None:
            self.results = {}
        if not self.task_id:
            self.task_id = new_id("task")


class AutonomousMode:
    """"Mach es einfach"-Modus."""
    
    def __init__(self, task_executor: Optional[Callable] = None):
        self.active = False
        self.autonomy_level = AutonomyLevel.SEMI_AUTONOMOUS
        self.task_queue: List[AutonomousTask] = []
        self.completed_tasks: List[AutonomousTask] = []
        self.failed_tasks: List[AutonomousTask] = []
        self.config = self._load_config()
        self.decision_callbacks: Dict[str, Callable] = {}
        self.task_executor = task_executor
        self._register_decision_callbacks()

    def _load_config(self) -> dict:
        """Lade Autonomie-Konfiguration."""
        default_config = {
            "default_autonomy_level": "semi_autonomous",
            "max_task_duration": 30,  # minutes
            "allow_file_operations": True,
            "allow_system_changes": False,
            "confirmation_threshold": "complex",
            "auto_retry": True,
            "max_retries": 3
        }
        
        try:
            if AUTONOMOUS_MODE_CONFIG_PATH.exists():
                loaded = json.loads(AUTONOMOUS_MODE_CONFIG_PATH.read_text(encoding="utf-8"))
                return {**default_config, **loaded}
        except Exception:
            pass
        
        return default_config
    
    def _save_config(self) -> None:
        """Speichere Autonomie-Konfiguration."""
        AUTONOMOUS_MODE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTONOMOUS_MODE_CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def _register_decision_callbacks(self) -> None:
        """Registriere Entscheidungs-Callbacks."""
        self.decision_callbacks = {
            "analyze_task": self._analyze_task_complexity,
            "check_permissions": self._check_permissions,
            "estimate_duration": self._estimate_duration,
            "determine_confirmation": self._determine_confirmation_need
        }
    
    def activate(self, autonomy_level: AutonomyLevel = AutonomyLevel.SEMI_AUTONOMOUS) -> None:
        """
        Aktiviere autonomen Modus.
        
        Args:
            autonomy_level: Autonomie-Level
        """
        self.active = True
        self.autonomy_level = autonomy_level
        print(f"[AutonomousMode] Activated with level: {autonomy_level.value}")
    
    def deactivate(self) -> None:
        """Deaktiviere autonomen Modus."""
        self.active = False
        print("[AutonomousMode] Deactivated")

    def set_task_executor(self, executor: Optional[Callable]) -> None:
        """Set the trusted executor used for real task execution."""
        if executor is not None and not callable(executor):
            raise TypeError("task executor must be callable")
        self.task_executor = executor
    
    def add_task(self, description: str) -> str:
        """
        Füge Aufgabe hinzu (Punkt 100).
        
        Args:
            description: Aufgabenbeschreibung
            
        Returns:
            Task ID
        """
        # Analysiere Aufgabe
        complexity = self._analyze_task_complexity(description)
        steps = self._generate_task_steps(description, complexity)
        required_tools = self._identify_required_tools(description)
        requires_confirmation = self._determine_confirmation_need(complexity)
        estimated_duration = self._estimate_duration(complexity, steps)
        
        task_id = new_id("task")
        
        task = AutonomousTask(
            task_id=task_id,
            description=description,
            complexity=complexity,
            steps=steps,
            required_tools=required_tools,
            requires_confirmation=requires_confirmation,
            estimated_duration=estimated_duration
        )
        
        self.task_queue.append(task)
        return task_id
    
    def _analyze_task_complexity(self, description: str) -> TaskComplexity:
        """Analysiere Aufgaben-Komplexität."""
        description_lower = description.lower()
        
        # Kritische Aufgaben zuerst prüfen (P1 fix).
        # Wortgrenzen statt Substring, sonst matcht "format" in "information".
        # 'remove'/'entferne' allein sind NICHT kritisch (z.B. 'Erinnerung entfernen'),
        # nur kombiniert mit destruktiven Objekten (Datei/Ordner/Verzeichnis).
        critical_keywords = [r"delete\w*", r"shutdown\w*", r"restart\w*", r"format\w*",
                             r"install\w*", r"lösch\w*", r"loesch\w*",
                             r"herunterfahren", r"neustart\w*"]
        destructive_objects = ("file", "folder", "directory", "datei", "ordner", "verzeichnis", "disk", "festplatte")
        if any(re.search(rf"\b{keyword}\b", description_lower) for keyword in critical_keywords):
            return TaskComplexity.CRITICAL
        if ("remove" in description_lower or "entferne" in description_lower) and any(
            obj in description_lower for obj in destructive_objects
        ):
            return TaskComplexity.CRITICAL

        # Komplexe Aufgaben
        complex_keywords = ["develop", "implement", "integrate", "optimize", "refactor", "debug"]
        if any(keyword in description_lower for keyword in complex_keywords):
            return TaskComplexity.COMPLEX

        # Moderate Aufgaben
        moderate_keywords = ["create", "move", "copy", "rename", "organize", "schedule"]
        if any(keyword in description_lower for keyword in moderate_keywords):
            return TaskComplexity.MODERATE
        
        # Einfache Aufgaben zuletzt prüfen
        simple_keywords = ["open", "close", "start", "stop", "show", "tell", "what", "how"]
        if any(keyword in description_lower for keyword in simple_keywords):
            return TaskComplexity.SIMPLE
        
        return TaskComplexity.MODERATE
    
    def _generate_task_steps(self, description: str, complexity: TaskComplexity) -> List[str]:
        """Generiere Aufgaben-Schritte."""
        if complexity == TaskComplexity.SIMPLE:
            return [
                "Understand the request",
                "Execute the action",
                "Verify the result"
            ]
        elif complexity == TaskComplexity.MODERATE:
            return [
                "Analyze the request",
                "Plan the approach",
                "Execute step by step",
                "Verify each step",
                "Confirm final result"
            ]
        elif complexity == TaskComplexity.COMPLEX:
            return [
                "Deep analysis of requirements",
                "Create detailed plan",
                "Break down into subtasks",
                "Execute each subtask",
                "Test intermediate results",
                "Integrate all components",
                "Final verification",
                "Documentation"
            ]
        else:  # CRITICAL
            return [
                "Risk assessment",
                "Backup current state",
                "Create detailed execution plan",
                "Confirm with user",
                "Execute with monitoring",
                "Verify after each step",
                "Rollback if issues",
                "Final verification",
                "Restore backup if needed"
            ]
    
    def _identify_required_tools(self, description: str) -> List[str]:
        """Identifiziere benötigte Tools."""
        tools = []
        description_lower = description.lower()
        
        if "file" in description_lower:
            tools.extend(["file_controller", "file_processor"])
        if "app" in description_lower or "program" in description_lower:
            tools.append("open_app")
        if "web" in description_lower or "search" in description_lower:
            tools.append("web_search")
        if "system" in description_lower or "computer" in description_lower:
            tools.extend(["computer_settings", "computer_control"])
        if "code" in description_lower or "programming" in description_lower:
            tools.extend(["code_helper", "dev_agent"])
        if "smart home" in description_lower:
            tools.append("smart_home")
        
        return tools
    
    def _determine_confirmation_need(self, complexity: TaskComplexity) -> bool:
        """Bestimme ob Bestätigung benötigt wird."""
        config_threshold = self.config.get("confirmation_threshold", "complex")
        
        if config_threshold == "simple":
            return True
        elif config_threshold == "moderate":
            return complexity in [TaskComplexity.MODERATE, TaskComplexity.COMPLEX, TaskComplexity.CRITICAL]
        elif config_threshold == "complex":
            return complexity in [TaskComplexity.COMPLEX, TaskComplexity.CRITICAL]
        elif config_threshold == "critical":
            return complexity == TaskComplexity.CRITICAL
        
        return False
    
    def _estimate_duration(self, complexity: TaskComplexity, steps: List[str]) -> int:
        """Schätze Aufgaben-Dauer."""
        base_minutes = {
            TaskComplexity.SIMPLE: 2,
            TaskComplexity.MODERATE: 10,
            TaskComplexity.COMPLEX: 30,
            TaskComplexity.CRITICAL: 60
        }
        
        return base_minutes.get(complexity, 15) + len(steps) * 2
    
    def _check_permissions(self, task: AutonomousTask) -> bool:
        """Prüfe Berechtigungen."""
        # Prüfe ob geforderte Aktionen erlaubt sind
        if any(name in task.required_tools for name in ("file_controller", "file_processor")):
            return self.config.get("allow_file_operations", True)
        
        if any(name in task.required_tools for name in ("computer_settings", "computer_control")):
            return self.config.get("allow_system_changes", False)
        
        return True
    
    def execute_next_task(self) -> Optional[dict]:
        """
        Führe nächste Aufgabe aus.
        
        Returns:
            Aufgabe-Ergebnis oder None
        """
        if not self.active:
            return {
                "status": "failed",
                "error": "Autonomous mode is not active"
            }

        if not self.task_queue:
            return None
        
        task = self.task_queue[0]
        
        # Prüfe Berechtigungen
        if not self._check_permissions(task):
            return {
                "task_id": task.task_id,
                "status": "failed",
                "error": "Insufficient permissions"
            }
        
        # Prüfe ob Bestätigung benötigt
        if task.requires_confirmation and self.autonomy_level != AutonomyLevel.FULLY_AUTONOMOUS:
            return {
                "task_id": task.task_id,
                "status": "awaiting_confirmation",
                "description": task.description,
                "steps": task.steps,
                "estimated_duration": task.estimated_duration
            }
        
        # Führe Aufgabe aus (inkl. Retries im selben Slot, damit ein
        # hartnäckiger Task die Queue nicht blockiert - Head-of-Line).
        task.status = "in_progress"
        
        if self.task_executor is None:
            result = self._execute_task(task)
            previous_results = task.results or {}
            attempt_history = list(previous_results.get("attempt_history", []))
            attempt_history.append(dict(result))
            result["retry_count"] = 0
            result["attempt_history"] = attempt_history
            task.results = result
            self._quarantine_failed_task(task, "no_executor")
            return result
        
        result = self._execute_task(task)
        max_retries = self.config.get("max_retries", 3)
        auto_retry = self.config.get("auto_retry", True)
        
        while not result.get("success"):
            task.status = "failed"
            previous_results = task.results or {}
            retry_count = previous_results.get("retry_count", 0)
            attempt_history = list(previous_results.get("attempt_history", []))
            attempt_history.append(dict(result))
            result["retry_count"] = retry_count
            result["attempt_history"] = attempt_history
            task.results = result
            
            if not auto_retry:
                self._quarantine_failed_task(task, "auto_retry_disabled")
                return result
            if retry_count >= max_retries:
                self._quarantine_failed_task(task, "max_retries_exhausted")
                return result
            
            # Retry im selben Slot - Folgeaufgaben rücken sofort nach.
            task.results["retry_count"] = retry_count + 1
            task.status = "retrying"
            task.current_step = 0
            result = self._execute_task(task)
        
        task.status = "completed"
        task.results = result
        self.completed_tasks.append(task)
        self.task_queue.remove(task)
        return result
    
    def _execute_task(self, task: AutonomousTask) -> dict:
        """Execute through a trusted adapter and never invent success."""
        if self.task_executor is None:
            return {
                "task_id": task.task_id,
                "success": False,
                "steps_completed": 0,
                "error": "No autonomous task executor is configured",
            }
        try:
            raw_result = self.task_executor(task)
            if isinstance(raw_result, dict):
                success = bool(raw_result.get("success"))
                output = raw_result.get("output", raw_result)
            else:
                success = bool(raw_result)
                output = raw_result
            result = {
                "task_id": task.task_id,
                "success": success,
                "steps_completed": len(task.steps) if success else 0,
                "output": output,
            }
            if isinstance(raw_result, dict) and "error" in raw_result:
                result["error"] = raw_result["error"]
            return result
        except Exception as exc:
            return {
                "task_id": task.task_id,
                "success": False,
                "steps_completed": 0,
                "error": str(exc),
            }
    
    def _quarantine_failed_task(self, task: AutonomousTask, reason: str) -> None:
        """Move a terminal failure out of the executable queue, retaining diagnostics."""
        if task in self.task_queue:
            self.task_queue.remove(task)
        task.status = "failed"
        if task.results is None:
            task.results = {}
        task.results["terminal_reason"] = reason
        if task not in self.failed_tasks:
            self.failed_tasks.append(task)
    
    def confirm_task(self, task_id: str, approved: bool) -> bool:
        """
        Bestätige Aufgabe (für semi-autonomen Modus).
        
        Args:
            task_id: Task ID
            approved: Ob genehmigt
            
        Returns:
            True wenn erfolgreich
        """
        for task in self.task_queue:
            if task.task_id == task_id:
                if approved:
                    task.requires_confirmation = False
                    return True
                else:
                    # Ablehnung - entferne aus Queue
                    self.task_queue.remove(task)
                    return True
        return False
    
    def get_task_status(self, task_id: str) -> Optional[dict]:
        """Gib Aufgaben-Status zurück."""
        # Suche in Queue
        for task in self.task_queue:
            if task.task_id == task_id:
                return {
                    "task_id": task.task_id,
                    "description": task.description,
                    "complexity": task.complexity.value,
                    "status": task.status,
                    "current_step": task.current_step,
                    "total_steps": len(task.steps),
                    "estimated_duration": task.estimated_duration
                }
        
        # Suche in completed
        for task in self.completed_tasks:
            if task.task_id == task_id:
                return {
                    "task_id": task.task_id,
                    "description": task.description,
                    "complexity": task.complexity.value,
                    "status": task.status,
                    "results": task.results
                }

        # Suche in endgültig fehlgeschlagenen Aufgaben
        for task in self.failed_tasks:
            if task.task_id == task_id:
                return {
                    "task_id": task.task_id,
                    "description": task.description,
                    "complexity": task.complexity.value,
                    "status": task.status,
                    "results": task.results
                }
        
        return None
    
    def get_queue_status(self) -> dict:
        """Gib Queue-Status zurück."""
        return {
            "active": self.active,
            "autonomy_level": self.autonomy_level.value,
            "pending_tasks": len(self.task_queue),
            "completed_tasks": len(self.completed_tasks),
            "failed_tasks": len(self.failed_tasks),
            "current_task": self.task_queue[0].task_id if self.task_queue else None
        }
    
    def set_autonomy_level(self, level: AutonomyLevel) -> None:
        """Setze Autonomie-Level."""
        self.autonomy_level = level
        self.config["default_autonomy_level"] = level.value
        self._save_config()
    
    def clear_queue(self) -> None:
        """Leere Aufgaben-Queue."""
        self.task_queue.clear()
    
    def get_completion_summary(self) -> dict:
        """Gib Zusammenfassung abgeschlossener Aufgaben."""
        if not self.completed_tasks:
            return {"total_completed": 0}
        
        total_duration = sum(t.estimated_duration for t in self.completed_tasks)
        by_complexity = {}
        
        for task in self.completed_tasks:
            comp = task.complexity.value
            if comp not in by_complexity:
                by_complexity[comp] = 0
            by_complexity[comp] += 1
        
        return {
            "total_completed": len(self.completed_tasks),
            "total_duration_minutes": total_duration,
            "by_complexity": by_complexity,
            "success_rate": len([t for t in self.completed_tasks if t.status == "completed"]) / len(self.completed_tasks)
        }


# Globale Instanz für einfache Nutzung
_autonomous_mode = None

def get_autonomous_mode() -> AutonomousMode:
    """Gibt die globale AutonomousMode Instanz zurück."""
    global _autonomous_mode
    if _autonomous_mode is None:
        _autonomous_mode = AutonomousMode()
    return _autonomous_mode
