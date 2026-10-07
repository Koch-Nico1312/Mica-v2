"""Failure paths and observed state for the five daily-assistance additions."""
import threading
import time
from unittest.mock import Mock
import pytest
from desktop.core.native_commands import LocalTimers, NativeCommands
from desktop.core.attachments import extract_attachment, attachment_changed
from desktop.core.work_routine import QuietPeriod, RoutineRunner, WorkRoutine, WorkRoutineStore
from desktop.core.window_observation import wait_for_app_window
from mica_shared.quick_commands import parse_quick_command


@pytest.mark.parametrize("message,seconds,old", [("Nein, zehn Minuten statt fünf", 600, 300),
    ("10 Sekunden statt 5 Sekunden", 10, 5), ("zwei Stunden statt zehn Minuten", 7200, 600)])
def test_spoken_timer_correction_grammar(message, seconds, old):
    assert parse_quick_command(message) == {"kind": "timer_correct", "seconds": seconds, "previous_seconds": old}
    assert parse_quick_command(message + " && shutdown") is None


def test_correction_changes_latest_only_and_stale_callback_cannot_fire():
    elapsed = Mock()
    timers = LocalTimers(elapsed)
    timers.start(300)
    first = next(iter(timers._items))
    timers.start(60)
    old_timer = timers._items[next(reversed(timers._items))]["timer"]
    assert "passt nicht" in timers.correct_latest(600, 300)
    assert "ab jetzt" in timers.correct_latest(600, 60)
    assert timers._items[first]["seconds"] == 300
    assert timers._items[next(reversed(timers._items))]["seconds"] == 600
    old_timer.function()
    elapsed.assert_not_called()
    timers.cancel_all()
    assert "kein Timer" in timers.correct_latest(600, 60)


def test_timer_correction_dispatch_has_no_core_or_model_dependency():
    client, timers = Mock(), Mock()
    timers.correct_latest.return_value = "Timer geändert."
    command = parse_quick_command("Nein, zehn Minuten statt fünf")
    assert NativeCommands(client, timers).execute(command, "Nein, zehn Minuten statt fünf") == "Timer geändert."
    timers.correct_latest.assert_called_once_with(600, 300)
    client.plan.assert_not_called()


def test_window_confirmation_waits_for_observed_state_and_cancellation():
    observer = Mock()
    observer.matches.side_effect = [False, True]
    assert wait_for_app_window("firefox", timeout=1, observer=observer)
    assert observer.matches.call_count == 2
    observer.matches.side_effect = None
    observer.matches.return_value = False
    assert not wait_for_app_window("firefox", timeout=0, observer=observer)
    cancelled = threading.Event()
    cancelled.set()
    observer.reset_mock()
    assert not wait_for_app_window("firefox", cancelled=cancelled, observer=observer)
    observer.matches.assert_not_called()


def test_window_title_cannot_impersonate_the_requested_program():
    from desktop.core.window_observation import WindowsObservation
    observer = WindowsObservation.__new__(WindowsObservation)
    observer.windows = Mock(return_value=[{"exe": "other.exe", "title": "Firefox", "hwnd": 1}])
    assert not observer.matches("firefox")
    observer.windows.return_value = [{"exe": "firefox.exe", "title": "A page", "hwnd": 1}]
    assert observer.matches("firefox")


def test_successful_dispatch_without_a_window_never_confirms_open():
    client = Mock()
    client.plan.return_value = {"plan": {"task_id": "a" * 32}}
    client.execute.return_value = {"status": "succeeded", "output": "Opened Firefox."}
    verify = Mock(return_value=False)
    commands = NativeCommands(client, Mock(), verify_window=verify)
    assert "konnte ich nicht bestätigen" in commands.execute(parse_quick_command("Öffne Firefox"), "Öffne Firefox")
    verify.assert_called_once_with("firefox", cancelled=None)
    verify.return_value = True
    assert commands.execute(parse_quick_command("Öffne Firefox"), "Öffne Firefox") == "Firefox geöffnet."


def test_legacy_host_launch_checks_window_and_does_not_retry_dispatched_action(monkeypatch):
    import desktop.actions.open_app as module
    monkeypatch.setattr(module, "_SYSTEM", "Windows")
    launcher = Mock(return_value=True)
    monkeypatch.setitem(module._OS_LAUNCHERS, "Windows", launcher)
    verify = Mock(return_value=False)
    monkeypatch.setattr("desktop.core.window_observation.wait_for_app_window", verify)
    assert module.open_app({"app_name": "firefox"}).startswith("Could not confirm")
    assert launcher.call_count == 1
    verify.return_value = True
    assert module.open_app({"app_name": "firefox"}) == "Opened firefox."


def test_same_size_document_change_and_missing_file_are_detected(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("Docker A", encoding="utf-8")
    doc = extract_attachment(str(path))
    assert not attachment_changed(doc)
    path.write_text("Docker B", encoding="utf-8")
    assert attachment_changed(doc)
    path.unlink()
    assert attachment_changed(doc)


def test_routine_configuration_roundtrip_and_arbitrary_program_rejection(tmp_path):
    store = WorkRoutineStore(tmp_path / "routine.json")
    assert not store.load().enabled
    routine = WorkRoutine(True, ["firefox", "editor"], 20, 40)
    store.save(routine)
    assert store.load() == routine
    with pytest.raises(ValueError):
        store.save(WorkRoutine(True, ["powershell && shutdown"]))
    assert store.load() == routine
    store.path.write_text('{"enabled":true,"apps":["cmd"]}', encoding="utf-8")
    assert not store.load().enabled


def test_aliases_cannot_open_the_same_application_twice():
    with pytest.raises(ValueError):
        WorkRoutine(True, ["editor", "notepad"]).validate()
    with pytest.raises(ValueError):
        WorkRoutine(True, ["vscode", "visual studio code"]).validate()


def test_routine_partial_failure_stops_before_timer_and_quiet():
    store, commands, quiet = Mock(), Mock(), QuietPeriod()
    store.load.return_value = WorkRoutine(True, ["editor", "firefox"])
    commands.execute.side_effect = ["Editor geöffnet.", "Der Befehl wartet auf deine Freigabe unter Betrieb."]
    answer = RoutineRunner(store, commands, quiet).run()
    assert "angehalten" in answer and "Freigabe" in answer
    commands.timers.start.assert_not_called()
    assert not quiet.active


def test_routine_success_orders_apps_timer_and_quiet_and_can_end():
    clock = [100.0]
    quiet = QuietPeriod(clock=lambda: clock[0])
    store, commands, changed = Mock(), Mock(), Mock()
    store.load.return_value = WorkRoutine(True, ["editor"], 30, 20)
    commands.execute.return_value = "Editor geöffnet."
    commands.timers.start.side_effect = lambda seconds: "Timer gestartet." if not quiet.active else "already quiet"
    runner = RoutineRunner(store, commands, quiet, changed)
    assert "Arbeitsmodus gestartet" in runner.run()
    commands.timers.start.assert_called_once_with(1800)
    assert quiet.active
    changed.assert_called_once()
    clock[0] += 1200
    assert not quiet.active
    quiet.begin(5)
    quiet.end()
    assert not quiet.active


def test_routine_disabled_cancelled_or_timer_capacity_cannot_start_quiet():
    store, commands, quiet = Mock(), Mock(), QuietPeriod()
    store.load.return_value = WorkRoutine()
    runner = RoutineRunner(store, commands, quiet)
    assert "zuerst" in runner.run()
    commands.execute.assert_not_called()
    store.load.return_value = WorkRoutine(True, [])
    cancelled = threading.Event()
    cancelled.set()
    assert "abgebrochen" in runner.run(cancelled=cancelled)
    commands.timers.start.assert_not_called()
    commands.timers.start.return_value = "Es laufen bereits acht Timer."
    assert "angehalten" in runner.run()
    assert not quiet.active


def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_changed_file_remains_old_until_explicit_reload(tmp_path, monkeypatch):
    app = qt_app(monkeypatch)
    from desktop.attachment_overlay import AttachmentOverlay
    panel = AttachmentOverlay()
    path = tmp_path / "note.txt"
    path.write_text("Docker A", encoding="utf-8")
    doc = extract_attachment(str(path))
    panel._ready(doc, "")
    path.write_text("Docker B", encoding="utf-8")
    panel._changed_files([doc["id"]], panel._generation)
    assert panel.snapshot()[0]["body"] == "Docker A"
    assert panel._documents[doc["id"]]["changed"]
    panel.reload_file(doc["id"])
    deadline = time.monotonic() + 3
    while panel._loading and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert panel.snapshot()[0]["body"] == "Docker B"
    assert panel.snapshot()[0]["id"] == doc["id"]
    assert not panel._documents[doc["id"]].get("changed")
    assert "local_path" not in panel.snapshot()[0]
    panel.close()


def test_work_routine_ui_is_reviewable_and_saves_explicit_selection(tmp_path, monkeypatch):
    app = qt_app(monkeypatch)
    from desktop.work_routine_dialog import WorkRoutineDialog
    store = WorkRoutineStore(tmp_path / "work.json")
    panel = WorkRoutineDialog(store=store)
    panel.enabled.setChecked(True)
    panel.apps["firefox"].setChecked(True)
    panel.focus.setValue(45)
    panel.quiet.setValue(60)
    panel.save()
    assert store.load() == WorkRoutine(True, ["firefox"], 45, 60)
    panel.close()
    app.processEvents()


def test_foreground_tracking_does_not_capture_automatically_and_ignores_mica(monkeypatch):
    app = qt_app(monkeypatch)
    from desktop.core.screen_help import ForegroundTracker
    import os
    observer, capture = Mock(), Mock()
    observer.foreground.return_value = {"pid": 1, "title": "Error", "minimized": False, "hwnd": 10}
    clock = [0.0]
    tracker = ForegroundTracker(observer=observer, capture=capture, clock=lambda: clock[0])
    tracker.poll()
    capture.assert_not_called()
    observer.foreground.return_value = {"pid": os.getpid(), "title": "Mica", "minimized": False}
    tracker.poll()
    assert tracker.target["title"] == "Error"
    errors = []
    tracker.failed.connect(errors.append)
    clock[0] = 301
    tracker.capture_async()
    assert errors and "zuerst" in errors[0]
    capture.assert_not_called()
    tracker.timer.stop()
    app.processEvents()


def test_capture_preview_requires_acceptance(monkeypatch):
    app = qt_app(monkeypatch)
    from PyQt6.QtGui import QImage
    from desktop.screen_help_dialog import ScreenHelpDialog
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(0xffffffff)
    preview = ScreenHelpDialog({"title": "Error"}, image)
    assert preview.result() == 0
    preview.reject()
    assert preview.result() == 0
    preview.accept()
    assert preview.result() == 1
    app.processEvents()


def test_capture_context_is_added_only_after_ocr_and_temporary_image_is_removed(monkeypatch):
    app = qt_app(monkeypatch)
    from desktop.attachment_overlay import AttachmentOverlay
    from PyQt6.QtGui import QImage
    from pathlib import Path
    paths = []
    def extract(path):
        paths.append(Path(path))
        assert Path(path).exists()
        return {"id": "d" * 32, "title": "window.png", "body": "Error 503", "source": "screenshot", "local_path": str(path)}
    monkeypatch.setattr("desktop.attachment_overlay.extract_attachment", extract)
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    image.fill(0xffffffff)
    panel = AttachmentOverlay()
    ready = []
    panel.capture_ready.connect(ready.append)
    panel.add_capture(image, "Docker error")
    assert not panel.snapshot()
    deadline = time.monotonic() + 3
    while panel._loading and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert panel.snapshot()[0]["body"] == "Error 503"
    assert "local_path" not in panel.snapshot()[0]
    assert ready == ["Fenster: Docker error"]
    assert paths and not paths[0].exists()
    panel.close()


def test_quiet_period_blocks_wake_and_popups_but_keeps_manual_voice_available(monkeypatch):
    from desktop.local_main import LocalMica
    from types import SimpleNamespace
    mica = LocalMica.__new__(LocalMica)
    mica.quiet = QuietPeriod()
    mica.quiet.begin(5)
    mica._restoring = mica._calibrating = False
    mica.ui = SimpleNamespace(muted=False, write_log=Mock(), show_content=Mock())
    mica.voice = SimpleNamespace(active=True, take_barge_audio=Mock(return_value=b""), start=Mock(return_value=True))
    mica.wake_word = SimpleNamespace(start=Mock(), stop=Mock())
    monkeypatch.setenv("MICA_WAKE_WORD_ENABLED", "1")
    mica._wake_detected()
    mica._voice_completed()
    mica._timer_elapsed("Timer abgelaufen.")
    mica.wake_word.start.assert_not_called()
    mica.ui.show_content.assert_not_called()
    mica.ui.write_log.assert_called_with("SYS: Timer abgelaufen.")
    assert mica._push_to_talk_start()
    mica.voice.start.assert_called_once()
    mica._quiet_ended()
    mica.wake_word.start.assert_not_called()
    mica.voice.active = False
    mica._voice_completed()
    mica.wake_word.start.assert_called_once()
