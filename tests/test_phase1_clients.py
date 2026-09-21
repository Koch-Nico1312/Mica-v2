from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.local_core_client import LocalCoreClient
from core.local_voice import CoreVoiceSession


class Phase1ClientTests(unittest.TestCase):
    def test_text_turn_sends_selected_mode(self) -> None:
        client = LocalCoreClient("https://127.0.0.1:8443")
        client._request = Mock(return_value={"reply": "ok"})

        client.turn("Status?", "monitoring")

        client._request.assert_called_once_with(
            "POST",
            "/v1/turns",
            json={"message": "Status?", "client": "pyqt", "conversation_mode": "monitoring"},
        )

    def test_profile_client_uses_local_profile_endpoints(self) -> None:
        client = LocalCoreClient("https://127.0.0.1:8443")
        client._request = Mock(return_value={"preferred_name": "Nico"})

        self.assertEqual(client.profile()["preferred_name"], "Nico")
        client.update_profile({"preferred_name": "Nico"})

        self.assertEqual(client._request.call_args_list[0].args, ("GET", "/v1/profile"))
        self.assertEqual(client._request.call_args_list[1].args, ("PATCH", "/v1/profile"))

    def test_voice_start_sends_mode_and_invalid_mode_falls_back(self) -> None:
        client = LocalCoreClient("https://127.0.0.1:8443")
        session = CoreVoiceSession(client, conversation_mode="technical")
        fallback = CoreVoiceSession(client, conversation_mode="unknown")
        self.assertEqual(session.conversation_mode, "technical")
        self.assertEqual(fallback.conversation_mode, "personal")

        source = Path(ROOT / "desktop" / "core" / "local_voice.py").read_text(encoding="utf-8")
        self.assertIn('"conversation_mode": self.conversation_mode', source)

    def test_pwa_sends_the_same_selected_mode_for_text_and_voice(self) -> None:
        source = Path(ROOT / "backend" / "web_ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="mode"', source)
        self.assertIn("conversation_mode:mode.value", source)
        self.assertIn('value="personal"', source)
        self.assertIn('value="technical"', source)
        self.assertIn('value="monitoring"', source)

    def test_pwa_profile_form_uses_only_allowlisted_profile_fields(self) -> None:
        source = Path(ROOT / "backend" / "web_ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-view="profile"', source)
        self.assertIn("fetch(endpoint('/v1/profile'))", source)
        self.assertIn("method:'PATCH'", source)
        for field in (
            "preferred_address", "communication_preferences", "important_topics", "relationship_context",
        ):
            self.assertIn(field, source)
        self.assertNotIn("profileFields.secret", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
