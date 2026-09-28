"""Windows PyQt shell backed exclusively by the local MICA Core API."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DESKTOP_DIR = Path(__file__).resolve().parent
for _path in (str(PROJECT_DIR), str(DESKTOP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.settings_store import load_desktop_feature_environment

# The settings UI persists a small allowlist of non-secret desktop switches in
# the project .env. Load those switches before any optional desktop components
# inspect their environment gates.
load_desktop_feature_environment(PROJECT_DIR)

from core.local_core_client import LocalCoreClient, LocalCoreError
from core.local_voice import CoreVoiceSession, WakeWordListener
from core.hardware_recommendation import current_provider_recommendation
from ui import MICA_UI_GENERATION, JarvisUI


if MICA_UI_GENERATION < 2:
    raise RuntimeError("The legacy MICA UI is no longer supported.")


class LocalMica:
    def __init__(self, ui: JarvisUI):
        self.ui = ui
        self.client = LocalCoreClient()
        self._request_lock = threading.Lock()
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
            conversation_mode=self.conversation_mode,
        )
        self.wake_word = WakeWordListener(
            self._wake_detected,
            on_error=lambda text: self.ui.write_log(f"WARN: {text}"),
        )
        self.ui.on_push_to_talk_start = self._push_to_talk_start
        self.ui.on_push_to_talk_stop = self.voice.finish
        self.ui.on_interrupt = self.voice.cancel
        self.ui.on_mute_change = self._mute_changed
        self.ui.on_feature_change = self._feature_changed

    def _push_to_talk_start(self) -> bool:
        self.wake_word.stop()
        return self.voice.start()

    def _wake_detected(self) -> None:
        # A settings click may race the detector's final audio block. Re-check
        # the live policy before opening a new recording session so switching
        # the feature off cannot trigger one last capture.
        if self.ui.muted or os.getenv("MICA_WAKE_WORD_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        self.ui.write_log("SYS: Hey Mica erkannt.")
        self.voice.start(auto_finalize=True)

    def _voice_completed(self) -> None:
        if not self.ui.muted and os.getenv("MICA_WAKE_WORD_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
            self.wake_word.start()

    def _mute_changed(self, muted: bool) -> None:
        if muted:
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
        if os.getenv("MICA_WAKE_WORD_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
            if self.wake_word.start():
                self.ui.write_log("SYS: Wake-Word 'Hey Mica' ist lokal aktiv.")
            else:
                self.ui.write_log("WARN: Wake-Word-Modell fehlt; Push-to-talk bleibt verfuegbar.")

    def handle_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return

        with self._request_lock:
            self.ui.set_state("THINKING")
            try:
                result = self.client.turn(text, self.conversation_mode)
                answer = result.get("reply") or "Ich habe darauf gerade keine Textantwort."
                self.ui.write_log(f"Mica: {answer}")
                self.ui.show_content("Mica", answer)
            except LocalCoreError as exc:
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
