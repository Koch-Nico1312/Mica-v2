"""
Performance Tests für alle neuen Module.
"""
import time
import sys
from pathlib import Path

# Füge Projekt-Pfad hinzu
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.speaker_recognition import SpeakerRecognition
from core.whisper_mode import WhisperMode
from core.offline_fallback import OfflineFallback
from core.intercom_mode import IntercomMode
from core.smart_home import SmartHomeManager, Light, Switch
from core.server_monitor import ServerMonitor
from core.automation import AutomationEngine, Action, ActionType
from core.organization import OrganizationManager, TaskStatus, TaskPriority
from core.learning import LearningManager, Subject
from core.autonomous_server_agent import AutonomousServerAgent
from core.personal_dashboard import PersonalDashboard
from core.mica_3d import Mica3DIntegration, ObjectType
from core.autonomous_mode import AutonomousMode


def test_speaker_recognition_performance():
    """Teste Sprechererkennung Performance."""
    print("\n=== Speaker Recognition Performance ===")
    sr = SpeakerRecognition()
    
    # Registrierung
    import numpy as np
    audio_samples = [np.random.randint(-1000, 1000, 1600).astype(np.int16) for _ in range(5)]
    
    start = time.time()
    success, message = sr.register_speaker("TestUser", audio_samples)
    reg_time = time.time() - start
    
    print(f"Registration: {reg_time*1000:.2f}ms")
    
    # Identifikation
    test_audio = np.random.randint(-1000, 1000, 1600).astype(np.int16)
    start = time.time()
    speaker, similarity = sr.identify_speaker(test_audio)
    ident_time = time.time() - start
    
    print(f"Identification: {ident_time*1000:.2f}ms")
    print(f"Total: {(reg_time + ident_time)*1000:.2f}ms")


def test_whisper_mode_performance():
    """Teste Flüstermodus Performance."""
    print("\n=== Whisper Mode Performance ===")
    wm = WhisperMode()
    
    import numpy as np
    quiet_audio = np.random.randint(-10, 10, 1600).astype(np.int16)
    
    start = time.time()
    mode, level = wm.detect_speech_mode(quiet_audio)
    detect_time = time.time() - start
    
    print(f"Detection: {detect_time*1000:.2f}ms")
    
    start = time.time()
    use_whisper = wm.should_use_whisper_response(quiet_audio)
    whisper_time = time.time() - start
    
    print(f"Whisper decision: {whisper_time*1000:.2f}ms")
    print(f"Total: {(detect_time + whisper_time)*1000:.2f}ms")


def test_smart_home_performance():
    """Teste Smart Home Performance."""
    print("\n=== Smart Home Performance ===")
    shm = SmartHomeManager()
    
    # Geräte hinzufügen
    start = time.time()
    for i in range(10):
        light = Light(f"light{i}", f"Lampe {i}", "living_room")
        shm.add_device(light)
    add_time = time.time() - start
    
    print(f"Add 10 devices: {add_time*1000:.2f}ms")
    
    # Steuerung
    start = time.time()
    for i in range(10):
        shm.control_device(f"light{i}", "turn_on")
    control_time = time.time() - start
    
    print(f"Control 10 devices: {control_time*1000:.2f}ms")
    print(f"Total: {(add_time + control_time)*1000:.2f}ms")


def test_automation_performance():
    """Teste Automatisierung Performance."""
    print("\n=== Automation Performance ===")
    ae = AutomationEngine()
    
    # Automation erstellen
    actions = [
        Action(f"action{i}", ActionType.SYSTEM_COMMAND, {"command": f"echo test{i}"}, f"Test {i}")
        for i in range(10)
    ]
    
    start = time.time()
    automation_id = ae.create_automation("Test Automation", "Test description", actions)
    create_time = time.time() - start
    
    print(f"Create automation: {create_time*1000:.2f}ms")
    
    # Automation auflisten
    start = time.time()
    automations = ae.list_automations()
    list_time = time.time() - start
    
    print(f"List automations: {list_time*1000:.2f}ms")
    print(f"Total: {(create_time + list_time)*1000:.2f}ms")


def test_organization_performance():
    """Teste Organisation Performance."""
    print("\n=== Organization Performance ===")
    om = OrganizationManager()
    
    # Aufgaben erstellen
    start = time.time()
    for i in range(10):
        om.create_task(f"Task {i}", f"Description {i}", TaskPriority.MEDIUM)
    create_time = time.time() - start
    
    print(f"Create 10 tasks: {create_time*1000:.2f}ms")
    
    # Aufgaben abrufen
    start = time.time()
    tasks = om.get_tasks()
    get_time = time.time() - start
    
    print(f"Get tasks: {get_time*1000:.2f}ms")
    print(f"Total: {(create_time + get_time)*1000:.2f}ms")


def test_learning_performance():
    """Teste Lernen Performance."""
    print("\n=== Learning Performance ===")
    lm = LearningManager()
    
    # Sitzungen aufzeichnen
    start = time.time()
    for i in range(10):
        lm.record_session(Subject.MATHEMATICS, f"Topic {i}", 30, 0.8)
    record_time = time.time() - start
    
    print(f"Record 10 sessions: {record_time*1000:.2f}ms")
    
    # Fortschrittsbericht
    start = time.time()
    report = lm.get_progress_report()
    report_time = time.time() - start
    
    print(f"Get progress report: {report_time*1000:.2f}ms")
    print(f"Total: {(record_time + report_time)*1000:.2f}ms")


def test_server_monitor_performance():
    """Teste Server-Monitor Performance."""
    print("\n=== Server Monitor Performance ===")
    sm = ServerMonitor()
    
    # Server-Status
    start = time.time()
    status = sm.get_server_status()
    status_time = time.time() - start
    
    print(f"Get server status: {status_time*1000:.2f}ms")
    
    # Disk-Space
    start = time.time()
    disk_info = sm.monitor_disk_space()
    disk_time = time.time() - start
    
    print(f"Monitor disk space: {disk_time*1000:.2f}ms")
    print(f"Total: {(status_time + disk_time)*1000:.2f}ms")


def test_dashboard_performance():
    """Teste Dashboard Performance."""
    print("\n=== Dashboard Performance ===")
    pd = PersonalDashboard()
    pd.initialize_default_widgets()
    
    # Daten aktualisieren
    start = time.time()
    data = pd.refresh_dashboard_data()
    refresh_time = time.time() - start
    
    print(f"Refresh dashboard: {refresh_time*1000:.2f}ms")
    
    # Layout abrufen
    start = time.time()
    layout = pd.get_dashboard_layout()
    layout_time = time.time() - start
    
    print(f"Get layout: {layout_time*1000:.2f}ms")
    print(f"Total: {(refresh_time + layout_time)*1000:.2f}ms")


def test_mica_3d_performance():
    """Teste MICA-3D Performance."""
    print("\n=== MICA-3D Performance ===")
    m3d = Mica3DIntegration()
    m3d.connect()
    
    # Objekte erstellen
    object_ids = []
    start = time.time()
    for i in range(10):
        obj_id = m3d.create_object(ObjectType.CUBE, f"Cube {i}", (i, i, i))
        object_ids.append(obj_id)
    create_time = time.time() - start
    
    print(f"Create 10 objects: {create_time*1000:.2f}ms")
    
    # Objekte bewegen
    start = time.time()
    for i, obj_id in enumerate(object_ids):
        m3d.move_object(obj_id, (i+1, i+1, i+1))
    move_time = time.time() - start
    
    print(f"Move 10 objects: {move_time*1000:.2f}ms")
    print(f"Total: {(create_time + move_time)*1000:.2f}ms")


def test_autonomous_mode_performance():
    """Teste Autonomen Modus Performance."""
    print("\n=== Autonomous Mode Performance ===")
    am = AutonomousMode()
    am.activate()
    
    # Aufgaben hinzufügen
    start = time.time()
    for i in range(10):
        am.add_task(f"Task {i}")
    add_time = time.time() - start
    
    print(f"Add 10 tasks: {add_time*1000:.2f}ms")
    
    # Queue-Status
    start = time.time()
    status = am.get_queue_status()
    status_time = time.time() - start
    
    print(f"Get queue status: {status_time*1000:.2f}ms")
    print(f"Total: {(add_time + status_time)*1000:.2f}ms")


def run_all_performance_tests():
    """Führe alle Performance-Tests aus."""
    print("=" * 60)
    print("PERFORMANCE TESTS")
    print("=" * 60)
    
    test_speaker_recognition_performance()
    test_whisper_mode_performance()
    test_smart_home_performance()
    test_automation_performance()
    test_organization_performance()
    test_learning_performance()
    test_server_monitor_performance()
    test_dashboard_performance()
    test_mica_3d_performance()
    test_autonomous_mode_performance()
    
    print("\n" + "=" * 60)
    print("PERFORMANCE TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    run_all_performance_tests()