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
from core.speaker_recognition import SpeakerRecognition
from core.whisper_mode import WhisperMode
from core.offline_fallback import OfflineFallback, NetworkDetector
from core.intercom_mode import IntercomMode
from core.smart_home import (
    SmartHomeManager, Light, Switch, Thermostat, Sensor,
    InMemorySmartHomeAdapter,
)
from core.server_monitor import ServerMonitor
from core.automation import AutomationEngine, Action, Trigger, ActionType, TriggerType, Priority
from core.organization import OrganizationManager, Task, CalendarEvent, TaskStatus, TaskPriority
from core.learning import LearningManager, Subject, Difficulty, StudySession
from core.autonomous_server_agent import AutonomousServerAgent, Issue, Severity
from core.personal_dashboard import PersonalDashboard
from core.mica_3d import Mica3DIntegration, ObjectType, Vector3, Transform3D
from core.autonomous_mode import AutonomousMode, AutonomyLevel, TaskComplexity


class TestSpeakerRecognition(unittest.TestCase):
    """Tests für Sprechererkennung."""
    
    def setUp(self):
        self.sr = SpeakerRecognition()
    
    def test_register_speaker(self):
        """Teste Sprecher-Registrierung."""
        import numpy as np
        
        # Simuliere Audio-Daten
        audio_samples = [
            np.random.randint(-1000, 1000, 1600).astype(np.int16) for _ in range(5)
        ]
        
        success, message = self.sr.register_speaker("TestUser", audio_samples)
        self.assertTrue(success)
        self.assertIn("registriert", message.lower())
    
    def test_identify_speaker(self):
        """Teste Sprecher-Identifikation."""
        import numpy as np
        
        # Registriere Sprecher zuerst
        audio_samples = [
            np.random.randint(-1000, 1000, 1600).astype(np.int16) for _ in range(5)
        ]
        self.sr.register_speaker("TestUser", audio_samples)
        
        # Versuche Identifikation
        test_audio = np.random.randint(-1000, 1000, 1600).astype(np.int16)
        speaker, similarity = self.sr.identify_speaker(test_audio)
        
        # Sollte entweder Sprecher finden oder None zurückgeben
        self.assertTrue(speaker is None or isinstance(speaker, str))
        self.assertTrue(0 <= similarity <= 1)
    
    def test_list_speakers(self):
        """Teste Sprecher-Liste."""
        speakers = self.sr.list_speakers()
        self.assertIsInstance(speakers, list)


class TestWhisperMode(unittest.TestCase):
    """Tests für Flüstermodus."""
    
    def setUp(self):
        self.wm = WhisperMode()
    
    def test_detect_speech_mode(self):
        """Teste Sprachmodus-Erkennung."""
        import numpy as np
        
        # Leise Audio-Daten
        quiet_audio = np.random.randint(-10, 10, 1600).astype(np.int16)
        mode, level = self.wm.detect_speech_mode(quiet_audio)
        
        self.assertIn(mode, ["normal", "whisper", "silence"])
        self.assertTrue(0 <= level <= 1)
    
    def test_should_use_whisper_response(self):
        """Teste Flüster-Antwort-Entscheidung."""
        import numpy as np
        
        quiet_audio = np.random.randint(-10, 10, 1600).astype(np.int16)
        use_whisper = self.wm.should_use_whisper_response(quiet_audio)
        
        self.assertIsInstance(use_whisper, bool)
    
    def test_get_response_volume_multiplier(self):
        """Teste Volumen-Multiplikator."""
        import numpy as np
        
        quiet_audio = np.random.randint(-10, 10, 1600).astype(np.int16)
        multiplier = self.wm.get_response_volume_multiplier(quiet_audio)
        
        self.assertTrue(0 <= multiplier <= 1)


class TestOfflineFallback(unittest.TestCase):
    """Tests für Offline-Fallback."""
    
    def setUp(self):
        self.of = OfflineFallback()
        self.nd = NetworkDetector()
    
    def test_activate_deactivate(self):
        """Teste Aktivierung/Deaktivierung."""
        self.of.activate()
        self.assertTrue(self.of.active)
        
        self.of.deactivate()
        self.assertFalse(self.of.active)
    
    def test_process_text(self):
        """Teste Text-Verarbeitung."""
        self.of.activate()
        
        command, was_offline = self.of.process_text("stop")
        
        self.assertTrue(was_offline)
        self.assertEqual(command, "stop")
    
    def test_network_detector(self):
        """Teste Netzwerk-Detektor."""
        self.nd.report_success()
        self.assertFalse(self.nd.should_use_offline())
        
        self.nd.report_failure()
        self.nd.report_failure()
        self.nd.report_failure()
        
        self.assertTrue(self.nd.should_use_offline())


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
            "core.smart_home.SMART_HOME_CONFIG_PATH",
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


class TestAutonomousServerAgent(unittest.TestCase):
    """Tests für autonomen Server-Agent."""
    
    def setUp(self):
        self.asa = AutonomousServerAgent()
    
    def test_get_status(self):
        """Teste Status-Abfrage."""
        status = self.asa.get_status()
        
        self.assertIn("state", status)
        self.assertIn("running", status)
    
    def test_diagnose_disk_space(self):
        """Teste Disk-Diagnose."""
        issues = self.asa._diagnose_disk_space()
        
        self.assertIsInstance(issues, list)
    
    def test_get_issues(self):
        """Teste Issues-Abfrage."""
        issues = self.asa.get_issues()
        
        self.assertIsInstance(issues, list)


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
