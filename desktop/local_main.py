"""Windows PyQt shell backed exclusively by the local MICA Core API."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DESKTOP_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from desktop.core.settings_store import load_desktop_feature_environment

# The settings UI persists a small allowlist of non-secret desktop switches in
# the project .env. Load those switches before any optional desktop components
# inspect their environment gates.
load_desktop_feature_environment(PROJECT_DIR)

from desktop.core.local_core_client import LocalCoreClient, LocalCoreError
from desktop.core.local_voice import CoreVoiceSession, WakeWordListener
from desktop.core.hardware_recommendation import current_provider_recommendation
from desktop.core.native_commands import NativeCommands, LocalTimers
from desktop.core.work_routine import QuietPeriod, RoutineRunner, WorkRoutineStore
from desktop.core.local_state import DATA_DIR
from desktop.ui import MICA_UI_GENERATION, JarvisUI


if MICA_UI_GENERATION < 2:
    raise RuntimeError("The legacy MICA UI is no longer supported.")


class LocalMica:
    def __init__(self, ui: JarvisUI):
        self.ui = ui
        self.client = LocalCoreClient()
        self.ui.use_backend_memory()
        self.ui._win._control_center.restore_busy.connect(self._restore_busy)
        self._request_lock = threading.RLock()
        self._restoring = False
        self._calibrating = False
        self.quiet = QuietPeriod()
        self._quiet_was_active = False
        self.timers = LocalTimers(self._timer_elapsed, path=DATA_DIR / 'timers.json')
        self.native_commands = NativeCommands(self.client, self.timers)
        self.routine = RoutineRunner(WorkRoutineStore(), self.native_commands, self.quiet, self._quiet_started,
                                     prepare_documents=self._prepare_routine_documents, apply_documents=self._apply_routine_documents)
        self.native_commands.routine_handler = self.routine.run
        self.native_commands.quiet_end = self._quiet_ended
        self.native_commands.workspace_handler = self._workspace_requested
        self.ui._win.on_workspace_operation = self._workspace_operation
        self.native_commands.preference_handler = self._preference_requested
        self.ui._win.on_preference_confirmation = self._confirm_preference
        self.ui._win.on_text_transform = self._transform_text
        self.ui._win.on_new_conversation = self._new_conversation
        self.ui._win.on_voice_calibration_change = self._calibration_changed
        configured_mode = os.getenv("MICA_CONVERSATION_MODE", "personal").strip().lower()
        self.conversation_mode = (
            configured_mode if configured_mode in {"personal", "technical", "monitoring"} else "personal"
        )
        self.voice = CoreVoiceSession(
            self.client,
            on_state=self.ui.set_state,
            on_level=self.ui.set_audio_level,
            on_transcript=lambda text: self.ui.write_log(f"Du: {text}"),
            on_reply=self._voice_reply,
            on_error=lambda text: self.ui.write_log(f"ERR: {text}"),
            on_complete=self._voice_completed,
            on_native_command=self._run_native,
            on_document=self._show_document,
            before_recording=self._sync_attachments,
            conversation_mode=self.conversation_mode,
            remember=lambda: self.ui.remember_conversations,
        )
        self.wake_word = WakeWordListener(
            self._wake_detected,
            on_error=lambda text: self.ui.write_log(f"WARN: {text}"),
        )
        self.ui._win.voice_ready_for_calibration = lambda: not self.voice.active
        self.ui.on_push_to_talk_start = self._push_to_talk_start
        self.ui.on_push_to_talk_stop = self.voice.finish
        self.ui.on_interrupt = self.voice.cancel
        self.ui.on_mute_change = self._mute_changed
        self.ui.on_feature_change = self._feature_changed
        self.ui.on_audio_device_change = self._audio_devices_changed
        self.ui._win._backend_memory_page.remember_changed.connect(self._privacy_changed)
        from PyQt6.QtCore import QTimer
        self._quiet_timer = QTimer(self.ui._win)
        self._quiet_timer.timeout.connect(self._quiet_tick)
        self._quiet_timer.start(1000)
        QTimer.singleShot(0, self._restore_timers)
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().aboutToQuit.connect(self.timers.shutdown)

    def _restore_timers(self):
        try:
            self.timers.restore()
        except (OSError, ValueError, TypeError) as error:
            self.ui.write_log('ERR: Gespeicherte Timer konnten nicht geladen werden: ' + str(error))

    def _workspace_requested(self, kind):
        self.ui._win._workspace_sig.emit(kind)
        return 'Arbeitsstand-Fenster geöffnet. Bitte Speichern oder Laden dort bestätigen.'

    def _preference_requested(self, draft):
        self.ui._win._preference_offer_sig.emit(draft)
        return 'Möchtest du diese Vorliebe dauerhaft speichern? Bitte den Vorschlag im geöffneten Fenster bestätigen oder verwerfen.'

    def _confirm_preference(self, draft, secret):
        with self._request_lock:
            if self._restoring or not self.ui.remember_conversations:
                raise ValueError('Speichern ist momentan gesperrt.')
            if secret:
                self.client.login(secret)
            return self.client.evolution_change('POST', '/v1/evolution/preferences', draft)

    def _transform_text(self, text, operation, language):
        with self._request_lock:
            if self._restoring:
                raise ValueError('Wiederherstellung läuft; bitte danach erneut versuchen.')
            return self.client.transform_text(text, operation, language)

    def _workspace_operation(self, action, payload, store):
        with self._request_lock:
            if self._restoring or not self.ui.remember_conversations:
                raise ValueError('Arbeitsstände sind während Wiederherstellung oder ohne Speicherung gesperrt.')
            if action == 'save':
                context = self.client.workspace_context()
                if not self.ui.remember_conversations:
                    raise ValueError('Gesprächsspeicherung wurde deaktiviert; Arbeitsstand nicht gespeichert.')
                return store.save(payload['documents'], context['task_id'], payload['next_step'], context.get('task_title', ''))
            data = store.validate(payload)
            # Resolve the current task first: deleted/disabled tasks must not be resurrected.
            self.client.resume_workspace(data['task_id'], data['next_step'], [
                {key: doc[key] for key in ('id', 'title', 'body', 'source')} for doc in data['documents']])
            return data

    def _timer_elapsed(self, text):
        self.ui.write_log("SYS: " + text)
        if not self.quiet.active:
            self.ui.show_content("Timer", text)

    def _quiet_started(self):
        self.wake_word.stop()

    def _quiet_ended(self):
        self.quiet.end()
        if not self.voice.active:
            self._voice_completed()

    def _quiet_tick(self):
        active = self.quiet.active
        self.ui._win._routine_button.setText("Abläufe · Ruhezeit" if active else "Abläufe")
        if self._quiet_was_active and not active:
            self.ui.write_log("SYS: Mica-Ruhezeit beendet.")
            if not self.voice.active:
                threading.Thread(target=self._voice_completed, daemon=True).start()
        self._quiet_was_active = active

    def _privacy_changed(self, remember: bool):
        if not remember and self.voice.active:
            self.voice.cancel()
        if not remember:
            threading.Thread(target=self._reset_dialog, daemon=True).start()

    def _sync_attachments(self):
        with self._request_lock:
            selected = getattr(self.ui._win, "selected_documents", lambda: [])()
            self.client.select_documents(selected)

    def _new_conversation(self):
        self.voice.cancel()
        self._reset_dialog()

    def _reset_dialog(self):
        with self._request_lock:
            try:
                self.client.clear_dialog()
                self.ui.write_log("SYS: Neues Gespräch gestartet; bisherige Gesprächsbezüge gelöscht.")
            except LocalCoreError as error:
                self.ui.write_log("ERR: Gespräch konnte nicht zurückgesetzt werden: " + str(error))

    def _run_native(self, command, message, cancelled=None):
        with self._request_lock:
            if self._restoring:
                return "Wiederherstellung läuft; bitte später erneut versuchen."
            return self.native_commands.execute(command, message, cancelled=cancelled)

    def _prepare_routine_documents(self, paths):
        from desktop.core.attachments import extract_attachment
        documents = [extract_attachment(path) for path in paths]
        if sum(len(doc['body']) for doc in documents) > 64000:
            raise ValueError('Die Ablaufdokumente dürfen zusammen höchstens 64.000 Zeichen enthalten.')
        return documents

    def _apply_routine_documents(self, documents):
        self.client.select_documents([{key: doc[key] for key in ('id', 'title', 'body', 'source')} for doc in documents])
        self.ui._win._routine_documents_sig.emit(documents)

    def _show_document(self, document):
        self.ui.show_content(document["title"], document.get("body", ""))

    def _audio_devices_changed(self) -> None:
        self.wake_word.stop()
        was_active = self.voice.active
        self.voice.cancel()
        self.ui.write_log("SYS: Audio-Geraete gespeichert; die naechste Aufnahme nutzt die neue Auswahl.")
        if not was_active:
            self._voice_completed()

    def _push_to_talk_start(self) -> bool:
        if self._restoring or self._calibrating:
            return False
        self.wake_word.stop()
        return self.voice.start()

    def _restore_busy(self, busy: bool):
        self._restoring = busy
        if busy:
            overlay = getattr(self.ui._win, "_voice_overlay", None)
            if overlay is not None:
                overlay._stop.set()
            self.voice.cancel()
            self.wake_word.stop()
        elif not self.voice.active:
            self._voice_completed()

    def _wake_detected(self) -> None:
        # A settings click may race the detector's final audio block. Re-check
        # the live policy before opening a new recording session so switching
        # the feature off cannot trigger one last capture.
        if self._restoring or self._calibrating or (hasattr(self, "quiet") and self.quiet.active) or self.ui.muted or os.getenv("MICA_WAKE_WORD_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        self.ui.write_log("SYS: Hey Mica erkannt.")
        self.voice.start(auto_finalize=True)

    def _voice_completed(self) -> None:
        audio = self.voice.take_barge_audio()
        if audio and not self._restoring and not self._calibrating and not self.ui.muted:
            self.ui.write_log("SYS: Sprachantwort unterbrochen; ich höre dir zu.")
            self.voice.start(auto_finalize=True, initial_audio=audio)
            return
        if not self._restoring and not self._calibrating and not (hasattr(self, "quiet") and self.quiet.active) and not self.ui.muted and os.getenv("MICA_WAKE_WORD_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
            self.wake_word.start()

    def _calibration_changed(self, busy):
        self._calibrating = busy
        if busy:
            self.voice.cancel()
            self.wake_word.stop()
        else:
            self._voice_completed()

    def _mute_changed(self, muted: bool) -> None:
        if muted:
            overlay = getattr(self.ui._win, "_voice_overlay", None)
            if overlay is not None:
                overlay._stop.set()
            self.voice.cancel()
            self.wake_word.stop()
        else:
            self._voice_completed()

    def _feature_changed(self, key: str, enabled: bool) -> None:
        if key != "MICA_WAKE_WORD_ENABLED":
            return
        if not enabled:
            self.wake_word.stop()
            self.ui.write_log("SYS: Aktivierungswort deaktiviert; Mikrofon-Listener gestoppt.")
            return
        if self.ui.muted:
            self.ui.write_log("SYS: Aktivierungswort gespeichert; es startet nach dem Entstummen.")
            return
        if hasattr(self, "quiet") and self.quiet.active:
            self.ui.write_log("SYS: Aktivierungswort startet nach der Mica-Ruhezeit.")
            return
        if self._calibrating:
            self.ui.write_log("SYS: Aktivierungswort startet nach dem Mikrofontest.")
            return
        if self.voice.active:
            self.ui.write_log("SYS: Aktivierungswort gespeichert; es startet nach dem aktuellen Sprachvorgang.")
            return
        if self.wake_word.start():
            self.ui.write_log("SYS: Wake-Word 'Hey Mica' ist lokal aktiv.")
        else:
            self.ui.write_log("WARN: Wake-Word-Modell fehlt oder Listener ist bereits aktiv.")

    def _voice_reply(self, text: str) -> None:
        self.ui.write_log(f"Mica: {text}")
        self.ui.show_content("Mica", text)

    def start(self) -> None:
        self.ui.set_state("CONNECTING")
        recommendation = current_provider_recommendation()
        if recommendation:
            self.ui.write_log(str(recommendation["display_message"]))
        try:
            health = self.client.health()
        except LocalCoreError as error:
            self.ui.set_state("OFFLINE")
            self.ui.write_log(f"ERR: {error}")
            return
        self.ui.set_state("LISTENING")
        if health.get("status") == "ready":
            self.ui.write_log("SYS: Mica ist ueber den lokalen Core bereit.")
        else:
            self.ui.write_log("WARN: Lokaler Core erreichbar; Phase-0-Checks sind noch nicht vollstaendig.")
        if not self.quiet.active and os.getenv("MICA_WAKE_WORD_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
            if self.wake_word.start():
                self.ui.write_log("SYS: Wake-Word 'Hey Mica' ist lokal aktiv.")
            else:
                self.ui.write_log("WARN: Wake-Word-Modell fehlt; Push-to-talk bleibt verfuegbar.")

    def handle_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return

        with self._request_lock:
            if self._restoring:
                self.ui.write_log('SYS: Wiederherstellung läuft; Eingabe nach Abschluss erneut senden.')
                return
            self.ui.set_state("THINKING")
            try:
                selected = getattr(self.ui._win, "selected_documents", lambda: [])()
                self.client.select_documents(selected)
                result = self.client.turn(text, self.conversation_mode, remember=self.ui.remember_conversations)
                if result.get("state") == "native_command":
                    result["reply"] = self._run_native(result["command"], result["message"])
                    try:
                        self.client.record_native_result(result["turn_id"], result["reply"])
                    except LocalCoreError:
                        self.ui.write_log("WARN: Das Befehlsergebnis konnte nicht zum Gesprächskontext hinzugefügt werden.")
                if result.get("state") == "stopped":
                    self.timers.cancel_all()
                answer = result.get("reply") or "Ich habe darauf gerade keine Textantwort."
                self.ui.write_log(f"Mica: {answer}")
                self.ui.show_content("Mica", answer)
                if result.get("document"):
                    self._show_document(result["document"])
            except (LocalCoreError, OSError, ValueError) as exc:
                self.ui.write_log(f"ERR: Lokale Antwort fehlgeschlagen: {exc}")
                self.ui.show_content("Fehler", str(exc))
            finally:
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")


def main() -> None:
    os.chdir(DESKTOP_DIR)
    ui = JarvisUI("assets/mica-orb-v2.png")
    mica = LocalMica(ui)
    ui.on_text_command = mica.handle_text
    threading.Thread(target=mica.start, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
