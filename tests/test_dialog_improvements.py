from __future__ import annotations
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend.services.api.app import create_app
from backend.services.common.dialog_sessions import DialogSessions
from desktop.core.attachments import extract_attachment
from desktop.core.native_commands import NativeCommands, LocalTimers
from desktop.core.local_core_client import LocalCoreError
from mica_shared.quick_commands import parse_quick_command

SESSION = "a" * 32
DOC = "b" * 32


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("MICA_API_TOKEN", "x" * 40)
    monkeypatch.setenv("MICA_LAYA_ENABLED", "0")
    monkeypatch.setenv("MICA_HINDSIGHT_ENABLED", "0")
    monkeypatch.setenv("MICA_PHASE3_ENABLED", "1")
    monkeypatch.setenv("MICA_ALLOWED_VOICE_ORIGINS", "https://mica.local")
    app = create_app(data_dir=tmp_path)
    runtime = app.state.runtime
    runtime._local_completion = Mock(return_value="Antwort aus dem Gespräch.")
    client = TestClient(app, headers={"X-Mica-API-Token": "x" * 40})
    return client, runtime


def turn(api_client, text, **kwargs):
    response = api_client.post("/v1/turns", json={"message": text, "session_id": SESSION, "remember": False, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def select(client, documents):
    response = client.post("/v1/dialog/context", json={"session_id": SESSION, "documents": documents})
    assert response.status_code == 200, response.text


def document(identifier=DOC, title="Docker.md", body="Docker läuft lokal.\nWeitere Notizen."):
    return {"id": identifier, "title": title, "body": body, "source": "text"}


def test_selected_document_search_follow_up_and_ambiguous_file_choice(dialog):
    client, runtime = dialog
    select(client, [document(), document("c" * 32, "Docker Server.md", "Docker auf Proxmox")])
    answer = turn(client, "Öffne Docker")
    assert answer["state"] == "clarification_required"
    assert len(answer["clarification"]["choices"]) == 2
    # Synchronizing unchanged attachments must preserve the pending question.
    select(client, [document(), document("c" * 32, "Docker Server.md", "Docker auf Proxmox")])
    answer = turn(client, "1")
    assert answer["document"]["id"] == DOC
    assert "Docker läuft lokal" in turn(client, "Such darin nach Docker")["reply"]
    runtime._local_completion.assert_not_called()
    assert not runtime.brain.documents()


def test_session_history_cross_client_and_clear(dialog):
    client, runtime = dialog
    turn(client, "Wir besprechen gerade Micas Mikrofon.")
    turn(client, "Wie verbessere ich das?", client="voice")
    assert "Micas Mikrofon" in runtime._local_completion.call_args.args[0]
    assert client.delete(f"/v1/dialog/{SESSION}").status_code == 200
    turn(client, "Wie verbessere ich das?")
    assert "Micas Mikrofon" not in runtime._local_completion.call_args.args[0]
    assert not runtime.brain.documents()


def test_deselect_document_removes_focus_and_its_text_from_model_context(dialog):
    client, runtime = dialog
    select(client, [document(body="Privates Dokumentgeheimnis")])
    turn(client, "Öffne Docker")
    select(client, [])
    answer = turn(client, "Such darin nach Geheimnis")
    assert answer["state"] == "clarification_required"
    turn(client, "Erkläre eine Sonne")
    assert "Dokumentgeheimnis" not in runtime._local_completion.call_args.args[0]


def test_reloaded_document_replaces_focus_and_removes_old_quotes(dialog):
    client, runtime = dialog
    select(client, [document(body="Docker OLD SECRET")])
    turn(client, "Öffne Docker")
    turn(client, "Such darin nach Docker")
    select(client, [document(body="Docker NEW VERSION")])
    answer = turn(client, "Such darin nach Docker")
    assert "NEW VERSION" in answer["reply"] and "OLD SECRET" not in answer["reply"]
    turn(client, "Erkläre den Inhalt")
    assert "OLD SECRET" not in runtime._local_completion.call_args.args[0]


def test_ambiguous_clock_requires_exact_choice_before_command(dialog):
    client, runtime = dialog
    first = turn(client, "Erinnere mich morgen um 8 an Hausaufgaben", remember=True, native_commands=True)
    assert first["state"] == "clarification_required" and "08:00" in first["reply"] and "20:00" in first["reply"]
    second = turn(client, "20 Uhr", remember=True, native_commands=True)
    assert second["state"] == "native_command"
    assert second["command"]["time"] == "20:00"
    assert "Hausaufgaben" in second["message"]
    runtime._local_completion.assert_not_called()


def test_spoken_clock_and_spoken_answer_are_resolved(dialog):
    client, runtime = dialog
    answer = turn(client, "Erinnere mich morgen um acht an Hausaufgaben", remember=True, native_commands=True)
    assert answer["state"] == "clarification_required"
    answer = turn(client, "um zwanzig Uhr", remember=True, native_commands=True)
    assert answer["command"]["time"] == "20:00"
    assert parse_quick_command("Lautstärke auf fünfzig Prozent")["value"] == 50


def test_native_result_is_bound_to_issued_turn_and_enters_only_memory(dialog):
    client, runtime = dialog
    issued = turn(client, "Öffne Editor", remember=True, native_commands=True)
    payload = {"session_id": SESSION, "turn_id": issued["turn_id"], "reply": "Editor geöffnet."}
    assert client.post("/v1/dialog/result", json={**payload, "session_id": "d" * 32}).status_code == 409
    assert client.post("/v1/dialog/result", json=payload).status_code == 200
    assert client.post("/v1/dialog/result", json=payload).status_code == 409
    turn(client, "Was wurde geöffnet?")
    assert "Editor geöffnet" in runtime._local_completion.call_args.args[0]
    assert not runtime.brain.documents()


@pytest.mark.parametrize("message,command,reply", [
    ("Timer für fünf Minuten", {"kind": "timer", "seconds": 300}, "Timer für fünf Minuten gestartet."),
    ("Nein, zehn Minuten statt fünf", {"kind": "timer_correct", "seconds": 600, "previous_seconds": 300}, "Timer geändert."),
    ("Arbeitsmodus starten", {"kind": "routine", "name": "work"}, "Arbeitsmodus gestartet.")])
def test_voice_native_command_waits_for_result_before_speaking(dialog, monkeypatch, message, command, reply):
    import httpx
    client, runtime = dialog
    runtime._local_completion.side_effect = ValueError("model offline")
    synthesized = []
    def dispatch(request):
        if request.url.path == "/v1/transcribe":
            return httpx.Response(200, json={"text": message})
        synthesized.append(json.loads(request.content)["text"])
        return httpx.Response(200, content=b"WAV")
    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(runtime, "httpx", SimpleNamespace(Timeout=httpx.Timeout, HTTPError=httpx.HTTPError,
        AsyncClient=lambda **kwargs: original_async_client(transport=httpx.MockTransport(dispatch), **kwargs)))
    with client.websocket_connect("/v1/voice", headers={"origin": "https://mica.local"}) as socket:
        socket.receive_json()
        socket.send_json({"command": "start", "input_mode": "push_to_talk", "state": "listening",
                          "session_id": SESSION, "native_commands": True})
        socket.receive_json()
        socket.send_bytes(b"\x00\x00" * 1600)
        socket.receive_json()
        socket.send_json({"command": "finalize", "input_mode": "push_to_talk", "state": "transcribing"})
        received = []
        while True:
            event = socket.receive_json()
            received.append(event)
            if event["type"] == "native_command":
                assert event["command"] == command
                assert not synthesized
                socket.send_json({"type": "native_command_result", "reply": reply})
            if event["type"] == "state" and event["state"] == "speaking":
                break
        assert socket.receive_bytes() == b"WAV"
    assert synthesized == [reply]
    runtime._local_completion.assert_not_called()
    with runtime.dialog_sessions.session(SESSION) as state:
        assert state.history[-1]["assistant"] == synthesized[0]


def test_desktop_voice_dispatch_sends_actual_result(monkeypatch):
    from desktop.core.local_voice import CoreVoiceSession
    from desktop.core.local_core_client import LocalCoreClient
    messages = [json.dumps({"type": "native_command", "command": {"kind": "timer", "seconds": 300},
                            "message": "Timer für fünf Minuten"}), b"WAV"]
    socket = Mock()
    socket.recv.side_effect = messages
    commands = Mock(return_value="Timer gestartet.")
    session = CoreVoiceSession(LocalCoreClient("https://localhost", api_token="test"), on_native_command=commands)
    monkeypatch.setattr(session, "_play_response", lambda *args: None)
    done = threading.Event()
    session._reader(socket, done)
    assert done.is_set()
    commands.assert_called_once_with({"kind": "timer", "seconds": 300}, "Timer für fünf Minuten", session._cancel)
    assert json.loads(socket.send.call_args.args[0])["reply"] == "Timer gestartet."


def test_selected_file_and_text_focus_are_shared_with_websocket_voice(dialog, monkeypatch):
    import httpx
    client, runtime = dialog
    select(client, [document()])
    turn(client, "Öffne Docker")
    speech = []
    def dispatch(request):
        if request.url.path.endswith("transcribe"):
            return httpx.Response(200, json={"text": "Such darin nach Docker"})
        speech.append(json.loads(request.content)["text"])
        return httpx.Response(200, content=b"WAV")
    original = httpx.AsyncClient
    monkeypatch.setattr(runtime, "httpx", SimpleNamespace(Timeout=httpx.Timeout, HTTPError=httpx.HTTPError,
        AsyncClient=lambda **kwargs: original(transport=httpx.MockTransport(dispatch), **kwargs)))
    with client.websocket_connect("/v1/voice", headers={"origin": "https://mica.local"}) as socket:
        socket.receive_json()
        socket.send_json({"command": "start", "input_mode": "push_to_talk", "state": "listening", "session_id": SESSION})
        socket.receive_json()
        socket.send_bytes(b"\0\0" * 1600)
        socket.receive_json()
        socket.send_json({"command": "finalize", "input_mode": "push_to_talk", "state": "transcribing"})
        while True:
            event = socket.receive_json()
            if event["type"] == "response":
                assert "Docker läuft lokal" in event["text"]
            if event["type"] == "state" and event["state"] == "speaking":
                break
        socket.receive_bytes()
    assert "Docker läuft lokal" in speech[0]
    runtime._local_completion.assert_not_called()


def test_native_commands_work_with_unavailable_model_and_respect_stop_and_privacy(dialog):
    client, runtime = dialog
    runtime._local_completion.side_effect = ValueError("model unavailable")
    for text in ("Lautstärke auf 30 Prozent", "Öffne Editor", "Timer für fünf Minuten",
                 "Nein, zehn Minuten statt fünf", "Arbeitsmodus starten", "Ruhemodus beenden"):
        result = turn(client, text, remember=True, native_commands=True)
        assert result["state"] == "native_command"
    private = turn(client, "Öffne Editor", native_commands=True)
    assert private["state"] == "completed" and "ohne Speicherung" in private["reply"]
    runtime.policy.set_emergency_stop(True)
    assert turn(client, "Öffne Editor", remember=True, native_commands=True)["state"] == "stopped"
    runtime._local_completion.assert_not_called()


def test_task_reference_clarification_then_mark_completed(dialog):
    client, runtime = dialog
    first = runtime.task_store.create_task("Docker prüfen", "Container prüfen")
    runtime.task_store.create_task("Docker sichern", "Backup prüfen")
    question = turn(client, "Zeige Aufgabe Docker")
    assert question["state"] == "clarification_required"
    turn(client, "Docker prüfen")
    result = turn(client, "Markiere diese Aufgabe als erledigt", remember=True)
    assert "erledigt" in result["reply"]
    assert runtime.task_store.get_task(first["id"])["status"] == "completed"
    runtime._local_completion.assert_not_called()


def test_cloud_opt_in_does_not_automatically_send_selected_documents(dialog, monkeypatch):
    client, runtime = dialog
    monkeypatch.setattr(runtime, "configured_cloud_provider", lambda: "openai_api")
    monkeypatch.setattr(runtime, "cloud_private_context_allowed", lambda: False)
    select(client, [document(body="PRIVATE-ATTACHMENT-TEXT")])
    turn(client, "Was ist eine Sonne?")
    assert "PRIVATE-ATTACHMENT-TEXT" not in runtime._local_completion.call_args.args[0]


def test_response_style_and_context_limits_are_validated(dialog):
    client, runtime = dialog
    turn(client, "Erkläre Docker", response_style="brief")
    assert "ein bis drei" in runtime._local_completion.call_args.kwargs["system_prompt"]
    assert runtime._local_completion.call_args.args[1] <= 192
    assert client.post("/v1/turns", json={"message": "Hi", "response_style": "unlimited"}).status_code == 422
    assert client.post("/v1/dialog/context", json={"session_id": SESSION, "documents": [document(body="x" * 32001)]}).status_code == 422
    assert client.post("/v1/dialog/context", json={"session_id": SESSION, "documents": [document(), document()]}).status_code == 422


def test_expiring_context_and_separate_sessions():
    now = [0]
    sessions = DialogSessions(ttl=10, maximum=2, clock=lambda: now[0])
    with sessions.session(SESSION) as state:
        state.record("private one", "one")
    with sessions.session("d" * 32) as state:
        assert not state.history
    now[0] = 11
    with sessions.session(SESSION) as state:
        assert not state.history


def test_busy_conversation_does_not_block_another_conversation():
    import time
    sessions = DialogSessions()
    entered, release, waiting, other_finished = [threading.Event() for _ in range(4)]
    def owner():
        with sessions.session(SESSION):
            entered.set()
            release.wait(3)
    def follower():
        waiting.set()
        with sessions.session(SESSION):
            pass
    def other():
        with sessions.session("c" * 32):
            other_finished.set()
    threads = [threading.Thread(target=fn) for fn in (owner, follower, other)]
    threads[0].start()
    assert entered.wait(1)
    threads[1].start()
    assert waiting.wait(1)
    time.sleep(0.02)
    threads[2].start()
    try:
        assert other_finished.wait(1)
    finally:
        release.set()
        for thread in threads:
            thread.join(2)


def test_full_session_registry_returns_actionable_429(dialog):
    client, runtime = dialog
    runtime.dialog_sessions.maximum = 1
    turn(client, "Hallo")
    response = client.post("/v1/turns", json={"message": "Hallo", "session_id": "c" * 32})
    assert response.status_code == 429


def test_clear_releases_capacity_for_new_conversations():
    sessions = DialogSessions(maximum=1)
    for i in range(40):
        identifier = f"{i:032x}"
        with sessions.session(identifier) as state:
            state.record("Hallo", "Hallo")
        sessions.clear(identifier)


@pytest.mark.parametrize("text,kind", [("Hey Mica, bitte öffne Editor", "app"), ("Timer auf 10 Sekunden", "timer"),
                                      ("Lautstärke auf 40%", "volume"), ("Timer stoppen", "timer_cancel")])
def test_exact_command_grammar(text, kind):
    assert parse_quick_command(text)["kind"] == kind


def test_untrusted_command_does_not_get_execution_authority():
    client, timers = Mock(), Mock()
    commands = NativeCommands(client, timers)
    assert parse_quick_command("Öffne Chrome && shutdown") is None
    answer = commands.execute({"kind": "app", "app_name": "powershell"}, "Öffne Editor")
    assert "nicht ausgeführt" in answer
    client.execute.assert_not_called()
    timers.start.assert_not_called()


def test_native_broker_approval_failure_and_success_are_honest():
    client = Mock()
    client.plan.return_value = {"plan": {"task_id": "e" * 32, "permission": {"approval_id": "f" * 32}}}
    commands = NativeCommands(client, Mock(), verify_window=lambda *args, **kwargs: True)
    command = parse_quick_command("Öffne Editor")
    client.execute.side_effect = LocalCoreError("approval", status_code=403)
    assert "Freigabe" in commands.execute(command, "Öffne Editor")
    client.execute.side_effect = None
    client.execute.return_value = {"status": "succeeded", "output": "Could not confirm launch"}
    assert "nicht erfolgreich" in commands.execute(command, "Öffne Editor")
    client.execute.return_value = {"status": "succeeded", "output": "Opened notepad."}
    assert commands.execute(command, "Öffne Editor") == "Editor geöffnet."
    assert client.execute.call_args.kwargs["idempotency_key"].startswith("quick:")


def test_cancel_during_plan_cannot_dispatch_the_command():
    cancelled = threading.Event()
    client = Mock()
    def plan(*args, **kwargs):
        cancelled.set()
        return {"plan": {"task_id": "e" * 32, "permission": {}}}
    client.plan.side_effect = plan
    commands = NativeCommands(client, Mock())
    assert commands.execute(parse_quick_command("Öffne Editor"), "Öffne Editor", cancelled=cancelled) == "Befehl abgebrochen."
    client.execute.assert_not_called()


def test_timer_fires_without_core_or_model_and_cancel_is_effective():
    done = threading.Event()
    timers = LocalTimers(lambda text: done.set())
    assert "gestartet" in timers.start(1)
    assert done.wait(3)
    timers.start(30)
    assert "gestoppt" in timers.cancel_latest()
    assert timers.status() == "Es läuft kein Timer."


def test_text_and_real_pdf_extraction(tmp_path):
    text = tmp_path / "notiz.md"
    text.write_text("Docker funktioniert lokal.", encoding="utf-8")
    assert extract_attachment(str(text))["body"] == "Docker funktioniert lokal."
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 30 700 Td (Docker is local.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    pdf = tmp_path / "notiz.pdf"
    with pdf.open("wb") as handle:
        writer.write(handle)
    result = extract_attachment(str(pdf))
    assert result["source"] == "pdf" and "Docker is local" in result["body"]


def test_visible_attachment_selection_and_removal(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from desktop.attachment_overlay import AttachmentOverlay
    app = QApplication.instance() or QApplication([])
    panel = AttachmentOverlay()
    panel._ready(document(), "")
    assert len(panel.snapshot()) == 1
    panel._toggle(DOC, False)
    assert not panel.snapshot()
    panel._toggle(DOC, True)
    panel.remove(DOC)
    assert not panel.snapshot()
    panel.deleteLater()
    app.processEvents()
