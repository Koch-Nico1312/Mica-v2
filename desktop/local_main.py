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

from desktop.core.local_core_client import LocalCoreClient, LocalCoreError, LocalCoreUnavailable
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
        self._active_project = None
        self._local_workspace = None
        self._offline_workspace = False
        self._last_voice_request = ''
        self._dictating = False
        self.quiet = QuietPeriod()
        self._quiet_was_active = False
        from desktop.core.timer_delivery import WindowsTimerDelivery
        self.timers = LocalTimers(self._timer_elapsed, path=DATA_DIR / 'timers.json',
            delivery=WindowsTimerDelivery(DATA_DIR / 'timers.json') if os.name == 'nt' else None,
            on_due=self._reminder_due)
        self.ui._win.on_reminder_snooze = self._reminder_snooze
        self.ui._win.reminder_client = self.client
        self._quiet_reminders = []
        self._quiet_reminders_lock = threading.Lock()
        self.native_commands = NativeCommands(self.client, self.timers)
        self.routine = RoutineRunner(WorkRoutineStore(), self.native_commands, self.quiet, self._quiet_started,
                                     prepare_documents=self._prepare_routine_documents, apply_documents=self._apply_routine_documents)
        self.native_commands.routine_handler = self.routine.run
        self.native_commands.routine_draft_handler = self._routine_draft_requested
        self.native_commands.document_drafts_handler = self._document_drafts_requested
        self.native_commands.review_cards_handler = self._review_cards_requested
        self.native_commands.task_planning_handler = self._task_planning_requested
        self.native_commands.outcome_handler = self._outcome_requested
        self.ui._win.on_task_planning = self._task_planning_operation
        self.ui._win.on_document_drafts = self._document_drafts_operation
        self.native_commands.dictation_handler = self._dictation_requested
        self.ui._win.on_dictation = self._dictate
        self.ui._win.on_dictation_state = self._dictation_state
        self.ui._win.on_dictation_record = self._record_dictation
        self.native_commands.quiet_end = self._quiet_ended
        self.native_commands.workspace_handler = self._workspace_requested
        self.native_commands.project_handler = self._project_requested
        self.native_commands.memory_handler = self._memory_requested
        self.native_commands.changes_handler = self._changes_requested
        self.native_commands.window_help_handler = self._window_help_requested
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
            on_transcript=self._voice_transcript,
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
        QTimer.singleShot(0, lambda: threading.Thread(target=self._restore_timers,
            name='mica-timer-restore', daemon=True).start())
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

    def _task_planning_requested(self, page, title=''):
        self.ui._win._task_planning_sig.emit(page, title)
        return 'Aufgaben und Tagesplanung geöffnet. Prüfe Dauern, freie Zeitfenster und Vorschläge. Offline-Änderungen werden erst nach deinem Abgleich übernommen.'

    def _outcome_requested(self):
        self.ui._win._outcome_sig.emit()
        return 'Ergebnisprüfung geöffnet. Wähle die Datei oder das gewünschte Fenster und den erwarteten Inhalt.'

    def _task_planning_operation(self, action, payload, store):
        with self._request_lock:
            if self._restoring or not self.ui.remember_conversations:
                raise ValueError('Aufgaben sind während Wiederherstellung oder ohne Speicherung gesperrt.')
            if action == 'refresh':
                return store.refresh(self.client)
            if action == 'preview':
                return store.preview(self.client)
            if action == 'stage':
                return store.stage(payload['task'], minutes=payload['minutes'], depends_on=payload['depends_on'])
            if action == 'steps':
                return store.stage_steps(payload['steps'], payload['parent'])
            if action == 'decompose':
                return self.client.decompose_task(payload['title'], payload['description'])
            if action == 'apply':
                return store.apply(self.client, payload['preview'])
            if action == 'accept_remote':
                return store.accept_remote(self.client, payload['reviewed'])
            if action == 'discard':
                return store.discard(payload['key'])
            raise ValueError('Unbekannter Aufgaben-Vorgang.')

    def _routine_draft_requested(self, draft):
        self.ui._win._routine_draft_sig.emit(draft)
        return 'Ablaufvorschlag geöffnet. Prüfe Programme, Unterlagen, Fokus und Pause und bestätige Speichern. Danach kannst du den Ablauf starten.'

    def _document_drafts_requested(self, kind, instruction):
        self.ui._win._document_drafts_sig.emit(kind, instruction)
        return 'Dokumentvorschläge geöffnet. Bitte Quellen, Aufgaben oder Lernkarten prüfen und die gewünschte Auswahl speichern.'

    def _review_cards_requested(self):
        self.ui._win._review_cards_sig.emit()
        return 'Fällige Lernkarten geöffnet.'

    def _dictation_requested(self):
        self.ui._win._dictation_sig.emit()
        return 'Diktatvorschau geöffnet. Aufnahme dort starten, Text prüfen und zum Einfügen kopieren.'

    def _dictation_state(self, active):
        if active and (self.ui.muted or self._restoring or self._calibrating):
            raise ValueError('Diktieren ist während Stummschaltung, Wiederherstellung oder Mikrofontest gesperrt.')
        self._dictating = active
        if active:
            self.voice.cancel()
            self.wake_word.stop()
        else:
            self._voice_completed()

    def _dictate(self, audio):
        with self._request_lock:
            if self._restoring or self.ui.muted:
                raise ValueError('Diktieren ist während Wiederherstellung oder Stummschaltung gesperrt.')
            return self.client.dictate(audio)

    def _record_dictation(self, stop, cancelled):
        import time
        from desktop.core.dictation import record_clip
        limit = time.monotonic() + 5
        while self.voice.active and not cancelled.wait(.05):
            if time.monotonic() >= limit:
                raise ValueError('Der vorherige Sprachvorgang wird noch beendet. Bitte erneut diktieren.')
        if cancelled.is_set():
            return b''
        if self.ui.muted or self._restoring or self._calibrating:
            raise ValueError('Mikrofonaufnahme ist momentan gesperrt.')
        return record_clip(stop, cancelled)

    def _document_drafts_operation(self, action, payload):
        with self._request_lock:
            if self._restoring:
                raise ValueError('Wiederherstellung läuft.')
            if action == 'draft':
                return self.client.document_drafts(payload['documents'], payload['kind'], payload['instruction'])
            if not self.ui.remember_conversations:
                raise ValueError('Zum Speichern bitte den Modus mit Speicherung aktivieren.')
            if payload['kind'] == 'cards':
                from desktop.core.flashcards import FlashcardStore
                FlashcardStore().add([item for _, item in payload['items']])
                return {'saved': [row for row, _ in payload['items']]}
            saved = []
            for row, item in payload['items']:
                source = item['source']
                try:
                    task = self.client.create_task_item(item['title'], 'Quelle: ' + source['title'] + ' · Zeile ' + str(source['line']) + '\n' + source['quote'], item['due_at'],
                        idempotency_key=item.get('idempotency_key'))
                except LocalCoreError as error:
                    return {'saved': saved, 'error': 'Weitere Aufgaben nicht gespeichert: ' + str(error)}
                saved.append(row)
                if item['due_at']:
                    from datetime import datetime
                    import math
                    try:
                        seconds = max(1, math.ceil(datetime.fromisoformat(item['due_at']).timestamp() - self.timers.wall_clock()))
                        self.timers.start(seconds, task_id=task['id'], label=task['title'])
                    except (OSError, ValueError) as error:
                        return {'saved': saved, 'error': 'Aufgabe gespeichert; Erinnerung nicht eingerichtet: ' + str(error)}
            return {'saved': saved}

    def _project_requested(self, name):
        self.ui._win._project_sig.emit(name)
        return 'Projektstand „' + name + '“ geöffnet. Bitte die gespeicherte Auswahl prüfen und Laden bestätigen.'

    def _memory_requested(self, query):
        self.ui._win._memory_project_sig.emit(query)
        return 'Gedächtnisübersicht für „' + query + '“ geöffnet. Herkunft, Bearbeiten und Löschen findest du dort.'

    def _changes_requested(self):
        self.ui._win._document_changes_sig.emit()
        return 'Dokumentvergleich geöffnet. Wähle eine gespeicherte Ausgangsfassung und vergleiche sie mit der aktuellen Datei.'

    def _window_help_requested(self, question):
        self.ui._win._window_help_sig.emit(question)
        return 'Fensterhilfe geöffnet. Prüfe die erfassten Inhalte, bevor du sie als Kontext verwendest.'

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
                offline = getattr(self, '_offline_workspace', False)
                def cached_context():
                    if getattr(self, '_active_project', None) == store.name(payload['project']) and getattr(self, '_local_workspace', None):
                        return self._local_workspace
                    try:
                        return store.load(payload['project'])
                    except FileNotFoundError:
                        return {}
                try:
                    context = self.client.workspace_context() if not offline else cached_context()
                except LocalCoreError as error:
                    if not isinstance(error, LocalCoreUnavailable) and error.status_code not in {502, 503, 504}:
                        raise
                    offline = True
                    context = cached_context()
                context = {'task_id': context.get('task_id'), 'task_title': context.get('task_title', '')}
                if not self.ui.remember_conversations:
                    raise ValueError('Gesprächsspeicherung wurde deaktiviert; Arbeitsstand nicht gespeichert.')
                data = store.save(payload['documents'], context['task_id'], payload['next_step'], context.get('task_title', ''), name=payload['project'],
                    last_step=payload.get('last_step', ''), remember_progress=payload.get('remember_progress', False))
                self._active_project = store.name(payload['project'])
                self._local_workspace = data
                self._offline_workspace = offline
                return {**data, 'offline': offline}
            data = store.validate(payload)
            # Resolve the current task first: deleted/disabled tasks must not be resurrected.
            try:
                self.client.resume_workspace(data['task_id'], data['next_step'], [
                    {key: doc[key] for key in ('id', 'title', 'body', 'source')} for doc in data['documents']])
                self._offline_workspace = False
            except LocalCoreError as error:
                if not isinstance(error, LocalCoreUnavailable) and error.status_code not in {502, 503, 504}:
                    raise
                if action == 'sync':
                    raise
                self._offline_workspace = True
            self._active_project = store.name(payload.get('project', 'standard'))
            self._local_workspace = data
            return {**data, 'offline': self._offline_workspace}

    def _record_project_progress(self, request):
        if self._active_project and self.ui.remember_conversations and not self._restoring:
            from desktop.core.workspace import ProjectWorkspaceStore
            try:
                ProjectWorkspaceStore().record_progress(self._active_project, request)
            except (OSError, ValueError) as error:
                self.ui.write_log('WARN: Projektschritt konnte nicht gespeichert werden: ' + str(error))

    def _voice_transcript(self, text):
        self._last_voice_request = text
        self.ui.write_log(f'Du: {text}')

    def _timer_elapsed(self, text):
        self.ui.write_log("SYS: " + text)

    def _reminder_due(self, record):
        if record.get('task_id'):
            try:
                task = self.client._request('GET', '/v1/task-items/' + record['task_id'])
                if task.get('status') in {'completed', 'cancelled'}:
                    return
            except LocalCoreError:
                pass
        with self._quiet_reminders_lock:
            if self.quiet.active:
                self._quiet_reminders.append(record)
                return
        self.ui._win._reminder_sig.emit(record)

    def _reminder_snooze(self, record, seconds):
        result = self.timers.start(seconds, task_id=record.get('task_id'), label=record.get('label', 'Timer abgelaufen.'))
        if 'gestartet' not in result:
            raise ValueError(result)
        return result

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
            with self._quiet_reminders_lock:
                pending, self._quiet_reminders = self._quiet_reminders, []
            for record in pending:
                self.ui._win._reminder_sig.emit(record)
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
            if getattr(self, '_offline_workspace', False):
                raise ValueError('Projekt ist offline geladen. Zuerst unter Arbeitsstand den lokalen Projektstand ausdrücklich mit dem Backend-Gespräch verbinden.')
            selected = getattr(self.ui._win, "selected_documents", lambda: [])()
            self.client.select_documents(selected)

    def _new_conversation(self):
        self.voice.cancel()
        self._reset_dialog()

    def _reset_dialog(self):
        with self._request_lock:
            try:
                self.client.clear_dialog()
                self._offline_workspace = False
                self._local_workspace = None
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
        if self._restoring or self._calibrating or self._dictating:
            return False
        self.wake_word.stop()
        return self.voice.start()

    def _restore_busy(self, busy: bool):
        self._restoring = busy
        if busy:
            dictation = getattr(self.ui._win, '_dictation_dialog', None)
            if dictation:
                dictation.cancel_capture()
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
        if self._restoring or self._calibrating or self._dictating or (hasattr(self, "quiet") and self.quiet.active) or self.ui.muted or os.getenv("MICA_WAKE_WORD_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        self.ui.write_log("SYS: Hey Mica erkannt.")
        self.voice.start(auto_finalize=True)

    def _voice_completed(self) -> None:
        if self._dictating:
            return
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
            dictation = getattr(self.ui._win, '_dictation_dialog', None)
            if dictation:
                dictation.cancel_capture()
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
        if self._dictating:
            self.ui.write_log('SYS: Aktivierungswort startet nach dem Diktiermodus.')
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
        if self._last_voice_request:
            self._record_project_progress(self._last_voice_request)
            self._last_voice_request = ''

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
                from mica_shared.quick_commands import parse_quick_command
                quick = parse_quick_command(text)
                local_openers = {'task_planning', 'outcome_check', 'workspace_save', 'workspace_resume', 'project_switch', 'review_cards'}
                if quick and quick['kind'] in local_openers:
                    if not self.ui.remember_conversations and quick['kind'] != 'outcome_check':
                        raise ValueError('Lokale gespeicherte Funktionen benötigen den Modus mit Speicherung.')
                    answer = self._run_native(quick, text)
                    self.ui.write_log('Mica: ' + answer)
                    self.ui.show_content('Mica', answer)
                    return
                if getattr(self, '_offline_workspace', False):
                    raise ValueError('Projekt ist offline geladen. Unter Arbeitsstand erst die Verbindung mit dem Backend-Gespräch bestätigen; lokale Aufgaben und Lernkarten bleiben nutzbar.')
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
                if result.get('state') not in {'native_command', 'stopped', 'failed'}:
                    self._record_project_progress(text)
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
