"""
Organisations- und Planungs-Features.
Implementiert Punkte 71-80: Organisation Funktionalität.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
ORGANIZATION_DATA_PATH = BASE_DIR / "memory" / "organization.json"


class TaskStatus(Enum):
    """Aufgaben-Status."""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Aufgaben-Priorität."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


@dataclass
class CalendarEvent:
    """Kalender-Ereignis."""
    event_id: str = ""
    title: str = ""
    description: str = ""
    start_time: str = ""  # ISO format datetime
    end_time: str = ""    # ISO format datetime
    location: str = ""
    attendees: List[str] = None
    reminder_minutes: int = 15
    created_at: str = ""
    
    def __post_init__(self):
        if self.attendees is None:
            self.attendees = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.event_id:
            self.event_id = f"event_{datetime.now().strftime('%Y%m%d%H%M%S')}"


@dataclass
class Task:
    """Aufgabe."""
    task_id: str = ""
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: Optional[str] = None  # ISO format date
    estimated_hours: float = 1.0
    completed_at: Optional[str] = None
    created_at: str = ""
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.task_id:
            self.task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}"


@dataclass
class TimeBlock:
    """Zeitblock für Planung."""
    block_id: str = ""
    title: str = ""
    start_time: str = ""  # ISO format datetime
    end_time: str = ""    # ISO format datetime
    task_id: Optional[str] = None
    category: str = "general"
    recurring: bool = False
    
    def __post_init__(self):
        if not self.block_id:
            self.block_id = f"block_{datetime.now().strftime('%Y%m%d%H%M%S')}"


class OrganizationManager:
    """Verwaltet Kalender, Aufgaben und Planung."""
    
    def __init__(self):
        self.events: Dict[str, CalendarEvent] = {}
        self.tasks: Dict[str, Task] = {}
        self.time_blocks: Dict[str, TimeBlock] = {}
        self.data = self._load_data()
        
    def _load_data(self) -> dict:
        """Lade Organisations-Daten."""
        default_data = {
            "events": {},
            "tasks": {},
            "time_blocks": {},
            "settings": {
                "default_reminder_minutes": 15,
                "timezone": "UTC",
                "working_hours": {"start": "09:00", "end": "17:00"}
            }
        }
        
        try:
            if ORGANIZATION_DATA_PATH.exists():
                loaded = json.loads(ORGANIZATION_DATA_PATH.read_text(encoding="utf-8"))
                return {**default_data, **loaded}
        except Exception:
            pass
        
        return default_data
    
    def _save_data(self) -> None:
        """Speichere Organisations-Daten."""
        ORGANIZATION_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        save_data = {
            "events": {k: asdict(v) for k, v in self.events.items()},
            "tasks": {k: self._convert_task_for_json(v) for k, v in self.tasks.items()},
            "time_blocks": {k: asdict(v) for k, v in self.time_blocks.items()},
            "settings": self.data.get("settings", {})
        }
    
    def _convert_task_for_json(self, task: Task) -> dict:
        """Konvertiere Task für JSON-Speicherung."""
        data = asdict(task)
        data["status"] = task.status.value
        data["priority"] = task.priority.value
        return data
        
        ORGANIZATION_DATA_PATH.write_text(
            json.dumps(save_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    # ── Kalender (Punkte 71-72) ────────────────────────────────────────────────
    
    def read_calendar(self, start_date: str, end_date: str) -> List[CalendarEvent]:
        """
        Lese Kalender für Zeitraum (Punkt 71).
        
        Args:
            start_date: Startdatum (ISO format)
            end_date: Enddatum (ISO format)
            
        Returns:
            Liste der Ereignisse im Zeitraum
        """
        events = []
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        
        for event in self.events.values():
            event_start = datetime.fromisoformat(event.start_time)
            if start <= event_start <= end:
                events.append(event)
        
        # Sortiere nach Startzeit
        events.sort(key=lambda e: e.start_time)
        return events
    
    def create_event(self, 
                    title: str, 
                    description: str, 
                    start_time: str, 
                    end_time: str,
                    location: str = "",
                    attendees: List[str] = None,
                    reminder_minutes: int = 15) -> str:
        """
        Erstelle Termin (Punkt 72).
        
        Args:
            title: Titel
            description: Beschreibung
            start_time: Startzeit (ISO format)
            end_time: Endzeit (ISO format)
            location: Ort
            attendees: Teilnehmer
            reminder_minutes: Erinnerung in Minuten
            
        Returns:
            Event ID
        """
        event_id = f"event_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        event = CalendarEvent(
            event_id=event_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            location=location,
            attendees=attendees or [],
            reminder_minutes=reminder_minutes
        )
        
        self.events[event_id] = event
        self._save_data()
        return event_id
    
    def get_upcoming_events(self, hours: int = 24) -> List[CalendarEvent]:
        """Gib anstehende Ereignisse zurück."""
        now = datetime.now()
        future = now + timedelta(hours=hours)
        
        upcoming = []
        for event in self.events.values():
            event_start = datetime.fromisoformat(event.start_time)
            if now <= event_start <= future:
                upcoming.append(event)
        
        upcoming.sort(key=lambda e: e.start_time)
        return upcoming
    
    # ── Erinnerungen (Punkt 73, 80) ───────────────────────────────────────────
    
    def set_reminder(self, 
                    message: str, 
                    reminder_time: str,
                    reminder_type: str = "once") -> str:
        """
        Setze Erinnerung (Punkt 73).
        
        Args:
            message: Erinnerungsnachricht
            reminder_time: Zeitpunkt (ISO format)
            reminder_type: "once", "daily", "weekly"
            
        Returns:
            Reminder ID
        """
        # Erinnerung als spezielles Event speichern
        reminder_id = f"reminder_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        event = CalendarEvent(
            event_id=reminder_id,
            title=f"Reminder: {message}",
            description=message,
            start_time=reminder_time,
            end_time=reminder_time,
            reminder_minutes=0,
            created_at=datetime.now().isoformat()
        )
        
        self.events[reminder_id] = event
        self._save_data()
        return reminder_id
    
    def get_due_reminders(self) -> List[CalendarEvent]:
        """Gib fällige Erinnerungen zurück (Punkt 80)."""
        now = datetime.now()
        due_reminders = []
        
        for event in self.events.values():
            if event.title.startswith("Reminder:"):
                event_time = datetime.fromisoformat(event.start_time)
                if event_time <= now:
                    due_reminders.append(event)
        
        return due_reminders
    
    # ── To-do-Liste (Punkt 74) ───────────────────────────────────────────────────
    
    def create_task(self, 
                   title: str, 
                   description: str, 
                   priority: TaskPriority = TaskPriority.MEDIUM,
                   due_date: Optional[str] = None,
                   estimated_hours: float = 1.0,
                   tags: List[str] = None) -> str:
        """
        Erstelle Aufgabe (Punkt 74).
        
        Args:
            title: Titel
            description: Beschreibung
            priority: Priorität
            due_date: Fälligkeitsdatum (ISO format)
            estimated_hours: Geschätzte Zeit in Stunden
            tags: Tags
            
        Returns:
            Task ID
        """
        task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        task = Task(
            task_id=task_id,
            title=title,
            description=description,
            status=TaskStatus.TODO,
            priority=priority,
            due_date=due_date,
            estimated_hours=estimated_hours,
            tags=tags or []
        )
        
        self.tasks[task_id] = task
        self._save_data()
        return task_id
    
    def get_tasks(self, 
                 status: Optional[TaskStatus] = None,
                 priority: Optional[TaskPriority] = None,
                 tag: Optional[str] = None) -> List[Task]:
        """
        Hole Aufgaben mit Filter (Punkt 74).
        
        Args:
            status: Optionaler Status-Filter
            priority: Optionaler Prioritäts-Filter
            tag: Optionaler Tag-Filter
            
        Returns:
            Gefilterte Aufgabenliste
        """
        tasks = list(self.tasks.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        if priority:
            tasks = [t for t in tasks if t.priority == priority]
        
        if tag:
            tasks = [t for t in tasks if tag in t.tags]
        
        return tasks
    
    def complete_task(self, task_id: str) -> bool:
        """Markiere Aufgabe als erledigt."""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.DONE
            self.tasks[task_id].completed_at = datetime.now().isoformat()
            self._save_data()
            return True
        return False
    
    def delete_task(self, task_id: str) -> bool:
        """Lösche Aufgabe."""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save_data()
            return True
        return False
    
    # ── Aufgaben-Priorisierung (Punkt 75) ────────────────────────────────────────
    
    def prioritize_tasks(self, task_ids: List[str], priorities: List[TaskPriority]) -> bool:
        """
        Priorisiere Aufgaben (Punkt 75).
        
        Args:
            task_ids: Liste der Task IDs
            priorities: Liste der Prioritäten
            
        Returns:
            True wenn erfolgreich
        """
        if len(task_ids) != len(priorities):
            return False
        
        for task_id, priority in zip(task_ids, priorities):
            if task_id in self.tasks:
                self.tasks[task_id].priority = priority
        
        self._save_data()
        return True
    
    def get_task_suggestions(self) -> List[Task]:
        """
        Gib Aufgaben-Vorschläge basierend auf Priorität und Fälligkeit.
        
        Returns:
            Sortierte Liste von Aufgaben
        """
        tasks = list(self.tasks.values())
        now = datetime.now()
        
        # Filtere nur nicht erledigte Aufgaben
        tasks = [t for t in tasks if t.status != TaskStatus.DONE]
        
        def task_score(task: Task) -> int:
            score = 0
            
            # Priorität
            score += task.priority.value * 10
            
            # Fälligkeit
            if task.due_date:
                due = datetime.fromisoformat(task.due_date)
                days_until_due = (due - now).days
                if days_until_due <= 0:
                    score += 50  # Überfällig
                elif days_until_due <= 1:
                    score += 30  # Morgen fällig
                elif days_until_due <= 7:
                    score += 10  # Diese Woche fällig
            
            return score
        
        tasks.sort(key=task_score, reverse=True)
        return tasks
    
    # ── Tagesplanung (Punkt 76) ───────────────────────────────────────────────────
    
    def create_daily_plan(self, date: str) -> dict:
        """
        Erstelle Tagesplan (Punkt 76).
        
        Args:
            date: Datum (ISO format)
            
        Returns:
            Tagesplan mit Aufgaben und Zeitblöcken
        """
        target_date = datetime.fromisoformat(date).date()
        
        # Aufgaben für diesen Tag
        day_tasks = []
        for task in self.tasks.values():
            if task.due_date:
                task_date = datetime.fromisoformat(task.due_date).date()
                if task_date == target_date:
                    day_tasks.append(task)
        
        # Ereignisse für diesen Tag
        day_events = []
        for event in self.events.values():
            event_date = datetime.fromisoformat(event.start_time).date()
            if event_date == target_date:
                day_events.append(event)
        
        # Zeitblöcke für diesen Tag
        day_blocks = []
        for block in self.time_blocks.values():
            block_date = datetime.fromisoformat(block.start_time).date()
            if block_date == target_date:
                day_blocks.append(block)
        
        return {
            "date": date,
            "tasks": [asdict(t) for t in day_tasks],
            "events": [asdict(e) for e in day_events],
            "time_blocks": [asdict(b) for b in day_blocks],
            "total_tasks": len(day_tasks),
            "total_events": len(day_events),
            "estimated_hours": sum(t.estimated_hours for t in day_tasks)
        }
    
    # ── Wochenplanung (Punkt 77) ─────────────────────────────────────────────────
    
    def create_weekly_plan(self, start_date: str) -> dict:
        """
        Erstelle Wochenplan (Punkt 77).
        
        Args:
            start_date: Startdatum der Woche (ISO format)
            
        Returns:
            Wochenplan mit täglicher Aufteilung
        """
        start = datetime.fromisoformat(start_date)
        weekly_plan = {}
        
        for day_offset in range(7):
            current_date = start + timedelta(days=day_offset)
            date_str = current_date.isoformat()
            daily_plan = self.create_daily_plan(date_str)
            weekly_plan[date_str] = daily_plan
        
        return {
            "start_date": start_date,
            "end_date": (start + timedelta(days=6)).isoformat(),
            "daily_plans": weekly_plan,
            "total_tasks": sum(p["total_tasks"] for p in weekly_plan.values()),
            "total_events": sum(p["total_events"] for p in weekly_plan.values())
        }
    
    # ── Zeitblöcke (Punkt 78) ────────────────────────────────────────────────────
    
    def create_time_block(self, 
                         title: str, 
                         start_time: str, 
                         end_time: str,
                         task_id: Optional[str] = None,
                         category: str = "general") -> str:
        """
        Erstelle Zeitblock (Punkt 78).
        
        Args:
            title: Titel
            start_time: Startzeit (ISO format)
            end_time: Endzeit (ISO format)
            task_id: Optionale zugehörige Aufgabe
            category: Kategorie
            
        Returns:
            Block ID
        """
        block_id = f"block_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        block = TimeBlock(
            block_id=block_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            task_id=task_id,
            category=category
        )
        
        self.time_blocks[block_id] = block
        self._save_data()
        return block_id
    
    def get_time_blocks(self, date: str) -> List[TimeBlock]:
        """Gib Zeitblöcke für ein Datum zurück."""
        target_date = datetime.fromisoformat(date).date()
        blocks = []
        
        for block in self.time_blocks.values():
            block_date = datetime.fromisoformat(block.start_time).date()
            if block_date == target_date:
                blocks.append(block)
        
        blocks.sort(key=lambda b: b.start_time)
        return blocks
    
    # ── Deadlines (Punkt 79) ────────────────────────────────────────────────────
    
    def get_upcoming_deadlines(self, days: int = 7) -> List[dict]:
        """
        Gib anstehende Deadlines zurück (Punkt 79).
        
        Args:
            days: Anzahl der Tage in die Zukunft
            
        Returns:
            Liste von Deadlines
        """
        now = datetime.now()
        future = now + timedelta(days=days)
        
        deadlines = []
        
        for task in self.tasks.values():
            if task.due_date and task.status != TaskStatus.DONE:
                due_date = datetime.fromisoformat(task.due_date)
                if now <= due_date <= future:
                    days_until = (due_date - now).days
                    deadlines.append({
                        "task_id": task.task_id,
                        "title": task.title,
                        "due_date": task.due_date,
                        "days_until": days_until,
                        "priority": task.priority.value,
                        "status": task.status.value
                    })
        
        # Sortiere nach Fälligkeit
        deadlines.sort(key=lambda d: d["days_until"])
        return deadlines
    
    def check_overdue_deadlines(self) -> List[dict]:
        """Prüfe überfällige Deadlines."""
        now = datetime.now()
        overdue = []
        
        for task in self.tasks.values():
            if task.due_date and task.status != TaskStatus.DONE:
                due_date = datetime.fromisoformat(task.due_date)
                if due_date < now:
                    days_overdue = (now - due_date).days
                    overdue.append({
                        "task_id": task.task_id,
                        "title": task.title,
                        "due_date": task.due_date,
                        "days_overdue": days_overdue,
                        "priority": task.priority.value
                    })
        
        overdue.sort(key=lambda d: d["days_overdue"], reverse=True)
        return overdue
    
    # ── Overall Status ───────────────────────────────────────────────────────────
    
    def get_overview(self) -> dict:
        """Gib overall Übersicht zurück."""
        now = datetime.now()
        
        task_counts = {
            "total": len(self.tasks),
            "todo": len([t for t in self.tasks.values() if t.status == TaskStatus.TODO]),
            "in_progress": len([t for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS]),
            "done": len([t for t in self.tasks.values() if t.status == TaskStatus.DONE])
        }
        
        upcoming_events = len(self.get_upcoming_events(hours=24))
        overdue_deadlines = len(self.check_overdue_deadlines())
        
        return {
            "tasks": task_counts,
            "events_today": upcoming_events,
            "overdue_deadlines": overdue_deadlines,
            "total_time_blocks": len(self.time_blocks),
            "last_updated": now.isoformat()
        }


# Globale Instanz für einfache Nutzung
_organization_manager = None

def get_organization_manager() -> OrganizationManager:
    """Gibt die globale OrganizationManager Instanz zurück."""
    global _organization_manager
    if _organization_manager is None:
        _organization_manager = OrganizationManager()
    return _organization_manager