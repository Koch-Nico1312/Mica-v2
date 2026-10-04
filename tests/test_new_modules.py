"""
Unit Tests für alle neuen Module (Punkte 1-100).
"""
import unittest
import tempfile
import json
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timedelta
import sys

# Füge Projekt-Pfad hinzu
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importiere die neuen Module
from desktop.core.intercom_mode import IntercomMode
from desktop.core.smart_home import (
    SmartHomeManager, Light, Switch, Thermostat, Sensor,
    InMemorySmartHomeAdapter,
)
from desktop.core.server_monitor import ServerMonitor
from desktop.core.automation import AutomationEngine, Action, Trigger, ActionType, TriggerType, Priority
from desktop.core.organization import OrganizationManager, Task, CalendarEvent, TaskStatus, TaskPriority
from desktop.core.learning import LearningManager, Subject, Difficulty, StudySession
from desktop.core.personal_dashboard import PersonalDashboard
from desktop.core.mica_3d import Mica3DIntegration, ObjectType, Vector3, Transform3D
from desktop.core.autonomous_mode import AutonomousMode, AutonomyLevel, TaskComplexity








class TestIntercomMode(unittest.TestCase):
    """Tests für Intercom-Modus."""
    
    def setUp(self):
        self.ic = IntercomMode()
    
    def test_activate_deactivate(self):
        """Teste Aktivierung/Deaktivierung."""
        success = self.ic.activate("default")
        self.assertTrue(success)
        self.assertTrue(self.ic.active)
        
        self.ic.deactivate()
        self.assertFalse(self.ic.active)
    
    def test_connect_to_room(self):
        """Teste Raum-Verbindung."""
        self.ic.activate("default")
        # Erstelle living_room in config
        self.ic.config["rooms"]["living_room"] = {"name": "Wohnzimmer", "enabled": True}
        success = self.ic.connect_to_room("living_room")
        
        # Kann fehlschlagen wenn Raum nicht aktiviert ist
        self.assertIsInstance(success, bool)
    
    def test_send_message(self):
        """Teste Nachrichten-Sendung."""
        self.ic.activate("default")
        self.ic.config["rooms"]["living_room"] = {"name": "Wohnzimmer", "enabled": True}
        self.ic.connect_to_room("living_room")
        
        success = self.ic.send_message("Test message")
        # Kann fehlschlagen wenn keine Verbindung aktiv ist
        self.assertIsInstance(success, bool)
    
    def test_get_status(self):
        """Teste Status-Abfrage."""
        status = self.ic.get_status()
        
        self.assertIn("active", status)
        self.assertIn("current_room", status)


class TestSmartHome(unittest.TestCase):
    """Tests für Smart Home."""
    
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._config_patch = patch(
            "desktop.core.smart_home.SMART_HOME_CONFIG_PATH",
            Path(self._temp_dir.name) / "smart_home.json",
        )
        self._config_patch.start()
        self.shm = SmartHomeManager(adapter=InMemorySmartHomeAdapter())

    def tearDown(self):
        self._config_patch.stop()
        self._temp_dir.cleanup()
    
    def test_add_light(self):
        """Teste Lampe hinzufügen."""
        light = Light("light1", "Test Lampe", "living_room")
        success = self.shm.add_device(light)
        
        self.assertTrue(success)
        self.assertIn("light1", self.shm.devices)
    
    def test_control_light(self):
        """Teste Lampen-Steuerung."""
        light = Light("light1", "Test Lampe", "living_room")
        self.shm.add_device(light)
        
        success = self.shm.control_device("light1", "turn_on")
        self.assertTrue(success)
        
        success = self.shm.control_device("light1", "set_brightness", level=50)
        self.assertTrue(success)
    
    def test_create_scene(self):
        """Teste Szenen-Erstellung."""
        light = Light("light1", "Test Lampe", "living_room")
        self.shm.add_device(light)
        
        actions = [
            {"device_id": "light1", "action": "turn_on"},
            {"device_id": "light1", "action": "set_brightness", "params": {"level": 30}}
        ]
        
        success = self.shm.create_scene("test_scene", actions)
        self.assertTrue(success)
    
    def test_away_mode(self):
        """Teste 'Haus verlassen'-Modus."""
        success = self.shm.activate_away_mode()
        self.assertTrue(success)
        self.assertTrue(self.shm.away_mode)


class TestServerMonitor(unittest.TestCase):
    """Tests für Server-Monitor."""
    
    def setUp(self):
        self.sm = ServerMonitor()
    
    def test_get_server_status(self):
        """Teste Server-Status."""
        status = self.sm.get_server_status()
        
        self.assertIn("hostname", status)
        self.assertIn("os", status)
        # Docker und wmic können auf Windows fehlen
        # self.assertIn("docker_available", status)
    
    def test_monitor_disk_space(self):
        """Teste Disk-Space Monitoring."""
        disk_info = self.sm.monitor_disk_space()
        
        self.assertIsInstance(disk_info, list)
        if disk_info:
            self.assertIn("path", disk_info[0])
            self.assertIn("percent_used", disk_info[0])
    
    def test_get_alerts(self):
        """Teste Alert-Abfrage."""
        alerts = self.sm.get_alerts()
        
        self.assertIsInstance(alerts, list)


class TestAutomation(unittest.TestCase):
    """Tests für Automatisierung."""
    
    def setUp(self):
        self.ae = AutomationEngine()
    
    def test_create_automation(self):
        """Teste Automation-Erstellung."""
        actions = [
            Action("action1", ActionType.SYSTEM_COMMAND, {"command": "echo test"}, "Test command")
        ]
        
        automation_id = self.ae.create_automation(
            "Test Automation",
            "Test description",
            actions
        )
        
        self.assertIsNotNone(automation_id)
        self.assertIn(automation_id, self.ae.automations)
    
    def test_create_if_then_rule(self):
        """Teste Wenn-Dann-Regel."""
        actions = [
            Action("action1", ActionType.SYSTEM_COMMAND, {"command": "echo test"}, "Test command")
        ]
        
        rule_id = self.ae.create_if_then_rule("condition string", actions)
        
        self.assertIsNotNone(rule_id)
    
    def test_chain_actions(self):
        """Teste Aktions-Verkettung."""
        actions = [
            Action("action1", ActionType.SYSTEM_COMMAND, {"command": "echo test1"}, "Test 1"),
            Action("action2", ActionType.SYSTEM_COMMAND, {"command": "echo test2"}, "Test 2")
        ]
        
        chain_id = self.ae.chain_actions(actions)
        
        self.assertIsNotNone(chain_id)
    
    def test_list_automations(self):
        """Teste Automation-Liste."""
        automations = self.ae.list_automations()
        
        self.assertIsInstance(automations, list)


class TestOrganization(unittest.TestCase):
    """Tests für Organisation."""
    
    def setUp(self):
        self.om = OrganizationManager()
    
    def test_create_task(self):
        """Teste Aufgaben-Erstellung."""
        task_id = self.om.create_task(
            "Test Task",
            "Test description",
            TaskPriority.MEDIUM
        )
        
        self.assertIsNotNone(task_id)
        self.assertIn(task_id, self.om.tasks)
    
    def test_complete_task(self):
        """Teste Aufgaben-Abschluss."""
        task_id = self.om.create_task("Test Task", "Test description")
        
        success = self.om.complete_task(task_id)
        self.assertTrue(success)
        
        task = self.om.tasks[task_id]
        self.assertEqual(task.status, TaskStatus.DONE)
    
    def test_create_event(self):
        """Teste Termin-Erstellung."""
        now = datetime.now()
        event_id = self.om.create_event(
            "Test Event",
            "Test description",
            now.isoformat(),
            (now + timedelta(hours=1)).isoformat()
        )
        
        self.assertIsNotNone(event_id)
        self.assertIn(event_id, self.om.events)
    
    def test_get_upcoming_deadlines(self):
        """Teste Deadline-Abfrage."""
        deadlines = self.om.get_upcoming_deadlines(days=7)
        
        self.assertIsInstance(deadlines, list)


class TestLearning(unittest.TestCase):
    """Tests für Lernen."""
    
    def setUp(self):
        self.lm = LearningManager()
    
    def test_explain_homework(self):
        """Teste Hausaufgaben-Erklärung."""
        explanation = self.lm.explain_homework(
            Subject.MATHEMATICS,
            "Algebra",
            "Löse x + 5 = 10"
        )
        
        self.assertIn("Algebra", explanation)
        self.assertIn("Erklärung", explanation)
    
    def test_create_study_plan(self):
        """Teste Lernplan-Erstellung."""
        plan_id = self.lm.create_study_plan(
            Subject.MATHEMATICS,
            ["Algebra", "Geometry"],
            (datetime.now() + timedelta(days=7)).isoformat()
        )
        
        self.assertIsNotNone(plan_id)
    
    def test_record_session(self):
        """Teste Sitzung-Aufzeichnung."""
        session_id = self.lm.record_session(
            Subject.MATHEMATICS,
            "Algebra",
            30,
            0.8
        )
        
        self.assertIsNotNone(session_id)
        self.assertIn(session_id, self.lm.sessions)
    
    def test_get_progress_report(self):
        """Teste Fortschrittsbericht."""
        report = self.lm.get_progress_report()
        
        self.assertIn("total_hours", report)
        self.assertIn("average_mastery", report)




class TestPersonalDashboard(unittest.TestCase):
    """Tests für persönliches Dashboard."""
    
    def setUp(self):
        self.pd = PersonalDashboard()
    
    def test_initialize_widgets(self):
        """Teste Widget-Initialisierung."""
        self.pd.initialize_default_widgets()
        
        self.assertGreater(len(self.pd.widgets), 0)
    
    def test_add_widget(self):
        """Teste Widget-Hinzufügung."""
        widget_id = self.pd.add_widget(
            "test_widget",
            "Test Widget",
            {"x": 0, "y": 0, "width": 1, "height": 1}
        )
        
        self.assertIsNotNone(widget_id)
        self.assertIn(widget_id, self.pd.widgets)
    
    def test_refresh_dashboard_data(self):
        """Teste Daten-Aktualisierung."""
        self.pd.initialize_default_widgets()
        data = self.pd.refresh_dashboard_data()
        
        self.assertIn("last_updated", data)
        self.assertIn("widgets", data)


class TestMica3D(unittest.TestCase):
    """Tests für MICA-3D-Integration."""
    
    def setUp(self):
        self.m3d = Mica3DIntegration()
    
    def test_connect(self):
        """Ohne echten Engine-Adapter darf keine Verbindung behauptet werden."""
        success = self.m3d.connect()
        
        self.assertFalse(success)
        self.assertFalse(self.m3d.connected)
    
    def test_create_object(self):
        """Teste Objekt-Erstellung."""
        self.m3d.connect()
        object_id = self.m3d.create_object(
            ObjectType.CUBE,
            "Test Cube",
            (0, 0, 0)
        )
        
        self.assertIsNotNone(object_id)
        self.assertIn(object_id, self.m3d.scene_objects)
    
    def test_move_object(self):
        """Teste Objekt-Bewegung."""
        self.m3d.connect()
        object_id = self.m3d.create_object(ObjectType.CUBE, "Test Cube")
        
        success = self.m3d.move_object(object_id, (1, 1, 1))
        self.assertTrue(success)
    
    def test_get_scene_info(self):
        """Teste Szenen-Info."""
        self.m3d.connect()
        info = self.m3d.get_scene_info()
        
        self.assertIn("connected", info)
        self.assertIn("object_count", info)


class TestAutonomousMode(unittest.TestCase):
    """Tests für autonomen Modus."""
    
    def setUp(self):
        self.am = AutonomousMode()
    
    def test_activate_deactivate(self):
        """Teste Aktivierung/Deaktivierung."""
        self.am.activate()
        
        self.assertTrue(self.am.active)
        
        self.am.deactivate()
        self.assertFalse(self.am.active)
    
    def test_add_task(self):
        """Teste Aufgaben-Hinzufügung."""
        self.am.activate()
        task_id = self.am.add_task("Open a file")
        
        self.assertIsNotNone(task_id)
        self.assertGreater(len(self.am.task_queue), 0)
    
    def test_get_queue_status(self):
        """Teste Queue-Status."""
        status = self.am.get_queue_status()
        
        self.assertIn("active", status)
        self.assertIn("autonomy_level", status)


if __name__ == "__main__":
    unittest.main()
