"""
"Mach es einfach"-Modus für autonome Aufgabenausführung.
Implementiert Punkt 100: "Mach es einfach"-Modus.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import sys


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
            self.task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}"


class AutonomousMode:
    """"Mach es einfach"-Modus."""
    
    def __init__(self):
        self.active = False
        self.autonomy_level = AutonomyLevel.SEMI_AUTONOMOUS
        self.task_queue: List[AutonomousTask] = []
        self.completed_tasks: List[AutonomousTask] = []
        self.config = self._load_config()
        self.decision_callbacks: Dict[str, Callable] = {}
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
        
        task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
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
        
        # Einfache Aufgaben
        simple_keywords = ["open", "close", "start", "stop", "show", "tell", "what", "how"]
        if any(keyword in description_lower for keyword in simple_keywords):
            return TaskComplexity.SIMPLE
        
        # Moderate Aufgaben
        moderate_keywords = ["create", "delete", "move", "copy", "rename", "organize", "schedule"]
        if any(keyword in description_lower for keyword in moderate_keywords):
            return TaskComplexity.MODERATE
        
        # Komplexe Aufgaben
        complex_keywords = ["develop", "implement", "integrate", "optimize", "refactor", "debug"]
        if any(keyword in description_lower for keyword in complex_keywords):
            return TaskComplexity.COMPLEX
        
        # Kritische Aufgaben
        critical_keywords = ["delete", "remove", "shutdown", "restart", "format", "install"]
        if any(keyword in description_lower for keyword in critical_keywords):
            return TaskComplexity.CRITICAL
        
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
        if "file_operations" in str(task.required_tools):
            return self.config.get("allow_file_operations", True)
        
        if "system_changes" in str(task.required_tools):
            return self.config.get("allow_system_changes", False)
        
        return True
    
    def execute_next_task(self) -> Optional[dict]:
        """
        Führe nächste Aufgabe aus.
        
        Returns:
            Aufgabe-Ergebnis oder None
        """
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
        
        # Führe Aufgabe aus
        task.status = "in_progress"
        result = self._execute_task(task)
        
        if result.get("success"):
            task.status = "completed"
            task.results = result
            self.completed_tasks.append(task)
            self.task_queue.remove(task)
        else:
            task.status = "failed"
            # Retry Logic
            if self.config.get("auto_retry", True):
                self._retry_task(task)
        
        return result
    
    def _execute_task(self, task: AutonomousTask) -> dict:
        """Führe einzelne Aufgabe aus."""
        # In echter Implementierung würde hier die tatsächliche Ausführung stattfinden
        # Für jetzt simuliert
        
        results = {
            "task_id": task.task_id,
            "success": True,
            "steps_completed": len(task.steps),
            "duration_minutes": task.estimated_duration,
            "output": f"Task completed: {task.description}"
        }
        
        return results
    
    def _retry_task(self, task: AutonomousTask) -> None:
        """Wiederhole Aufgabe."""
        max_retries = self.config.get("max_retries", 3)
        
        retry_count = task.results.get("retry_count", 0) if task.results else 0
        
        if retry_count < max_retries:
            # Setze Aufgabe an Anfang der Queue
            if task in self.task_queue:
                self.task_queue.remove(task)
            self.task_queue.insert(0, task)
            
            if task.results is None:
                task.results = {}
            task.results["retry_count"] = retry_count + 1
    
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
        
        return None
    
    def get_queue_status(self) -> dict:
        """Gib Queue-Status zurück."""
        return {
            "active": self.active,
            "autonomy_level": self.autonomy_level.value,
            "pending_tasks": len(self.task_queue),
            "completed_tasks": len(self.completed_tasks),
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