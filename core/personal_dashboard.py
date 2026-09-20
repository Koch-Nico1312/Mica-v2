"""
Persönliches Dashboard für zentrale Übersicht.
Implementiert Punkt 98: Persönliches Dashboard.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
DASHBOARD_CONFIG_PATH = BASE_DIR / "config" / "dashboard.json"


@dataclass
class DashboardWidget:
    """Dashboard Widget."""
    widget_id: str = ""
    widget_type: str = ""
    title: str = ""
    position: dict = None  # {"x": 0, "y": 0, "width": 2, "height": 1}
    data_source: str = ""
    refresh_interval: int = 60  # seconds
    enabled: bool = True
    
    def __post_init__(self):
        if self.position is None:
            self.position = {"x": 0, "y": 0, "width": 2, "height": 1}
        if not self.widget_id:
            self.widget_id = f"widget_{datetime.now().strftime('%Y%m%d%H%M%S')}"


class PersonalDashboard:
    """Persönliches Dashboard."""
    
    def __init__(self):
        self.widgets: Dict[str, DashboardWidget] = {}
        self.config = self._load_config()
        self.dashboard_data = {}
        
    def _load_config(self) -> dict:
        """Lade Dashboard Konfiguration."""
        default_config = {
            "layout": "grid",
            "theme": "dark",
            "refresh_interval": 30,
            "default_widgets": [
                {
                    "widget_type": "system_status",
                    "title": "System Status",
                    "position": {"x": 0, "y": 0, "width": 2, "height": 1}
                },
                {
                    "widget_type": "tasks",
                    "title": "Today's Tasks",
                    "position": {"x": 2, "y": 0, "width": 2, "height": 1}
                },
                {
                    "widget_type": "calendar",
                    "title": "Upcoming Events",
                    "position": {"x": 0, "y": 1, "width": 2, "height": 1}
                },
                {
                    "widget_type": "weather",
                    "title": "Weather",
                    "position": {"x": 2, "y": 1, "width": 1, "height": 1}
                },
                {
                    "widget_type": "smart_home",
                    "title": "Smart Home",
                    "position": {"x": 3, "y": 1, "width": 1, "height": 1}
                }
            ]
        }
        
        try:
            if DASHBOARD_CONFIG_PATH.exists():
                loaded = json.loads(DASHBOARD_CONFIG_PATH.read_text(encoding="utf-8"))
                return {**default_config, **loaded}
        except Exception:
            pass
        
        return default_config
    
    def _save_config(self) -> None:
        """Speichere Dashboard Konfiguration."""
        DASHBOARD_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        DASHBOARD_CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def initialize_default_widgets(self) -> None:
        """Initialisiere Standard-Widgets."""
        for i, widget_config in enumerate(self.config.get("default_widgets", [])):
            widget_id = f"widget_{i}"
            widget = DashboardWidget(
                widget_id=widget_id,
                widget_type=widget_config["widget_type"],
                title=widget_config["title"],
                position=widget_config["position"],
                data_source="auto",
                enabled=True
            )
            self.widgets[widget_id] = widget
    
    def add_widget(self, 
                  widget_type: str, 
                  title: str, 
                  position: dict,
                  data_source: str = "auto") -> str:
        """
        Füge Widget hinzu.
        
        Args:
            widget_type: Typ des Widgets
            title: Titel
            position: Position im Grid
            data_source: Datenquelle
            
        Returns:
            Widget ID
        """
        widget_id = f"widget_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        widget = DashboardWidget(
            widget_id=widget_id,
            widget_type=widget_type,
            title=title,
            position=position,
            data_source=data_source,
            enabled=True
        )
        
        self.widgets[widget_id] = widget
        return widget_id
    
    def remove_widget(self, widget_id: str) -> bool:
        """Entferne Widget."""
        if widget_id in self.widgets:
            del self.widgets[widget_id]
            return True
        return False
    
    def update_widget_position(self, widget_id: str, position: dict) -> bool:
        """Aktualisiere Widget-Position."""
        if widget_id in self.widgets:
            self.widgets[widget_id].position = position
            return True
        return False
    
    def refresh_dashboard_data(self) -> dict:
        """
        Aktualisiere Dashboard-Daten.
        
        Returns:
            Aktualisierte Dashboard-Daten
        """
        self.dashboard_data = {
            "last_updated": datetime.now().isoformat(),
            "widgets": {}
        }
        
        # System Status
        try:
            from actions.system_monitor import get_system_status
            system_status = get_system_status()
            self.dashboard_data["widgets"]["system_status"] = system_status
        except Exception:
            self.dashboard_data["widgets"]["system_status"] = {"error": "System status unavailable"}
        
        # Tasks
        try:
            from core.organization import get_organization_manager
            org_mgr = get_organization_manager()
            tasks = org_mgr.get_tasks()
            self.dashboard_data["widgets"]["tasks"] = [asdict(t) for t in tasks[:5]]
        except Exception:
            self.dashboard_data["widgets"]["tasks"] = []
        
        # Calendar
        try:
            from core.organization import get_organization_manager
            org_mgr = get_organization_manager()
            events = org_mgr.get_upcoming_events(hours=24)
            self.dashboard_data["widgets"]["calendar"] = [asdict(e) for e in events[:5]]
        except Exception:
            self.dashboard_data["widgets"]["calendar"] = []
        
        # Weather
        try:
            from actions.weather_report import weather_action
            weather = weather_action({"city": "Local"})
            self.dashboard_data["widgets"]["weather"] = {"weather": weather}
        except Exception:
            self.dashboard_data["widgets"]["weather"] = {"error": "Weather unavailable"}
        
        # Smart Home
        try:
            from core.smart_home import get_smart_home_manager
            shm = get_smart_home_manager()
            device_states = shm.get_device_states()
            self.dashboard_data["widgets"]["smart_home"] = device_states
        except Exception:
            self.dashboard_data["widgets"]["smart_home"] = {}
        
        # Learning Progress
        try:
            from core.learning import get_learning_manager
            learn_mgr = get_learning_manager()
            progress = learn_mgr.get_learning_overview()
            self.dashboard_data["widgets"]["learning"] = progress
        except Exception:
            self.dashboard_data["widgets"]["learning"] = {}
        
        # Server Status
        try:
            from core.server_monitor import get_server_monitor
            server_mon = get_server_monitor()
            server_status = server_mon.get_overall_status()
            self.dashboard_data["widgets"]["server"] = server_status
        except Exception:
            self.dashboard_data["widgets"]["server"] = {}
        
        return self.dashboard_data
    
    def get_dashboard_layout(self) -> dict:
        """Gib Dashboard-Layout zurück."""
        return {
            "layout": self.config.get("layout", "grid"),
            "theme": self.config.get("theme", "dark"),
            "widgets": [asdict(w) for w in self.widgets.values() if w.enabled],
            "data": self.dashboard_data
        }
    
    def customize_dashboard(self, layout: str = "grid", theme: str = "dark") -> None:
        """Passe Dashboard an."""
        self.config["layout"] = layout
        self.config["theme"] = theme
        self._save_config()


# Globale Instanz für einfache Nutzung
_personal_dashboard = None

def get_personal_dashboard() -> PersonalDashboard:
    """Gibt die globale PersonalDashboard Instanz zurück."""
    global _personal_dashboard
    if _personal_dashboard is None:
        _personal_dashboard = PersonalDashboard()
        _personal_dashboard.initialize_default_widgets()
    return _personal_dashboard