import os
import unittest
from unittest import mock

from core.tts import (
    DEFAULT_EDGE_FEMALE_VOICE,
    DEFAULT_ELEVENLABS_FEMALE_VOICE_ID,
    DEFAULT_KOKORO_FEMALE_VOICE,
    create_tts_player,
    select_female_tts_voice,
)
from core.windows_dpi import configure_qt_dpi_startup
from memory import config_manager


class FemaleVoiceDefaultsTests(unittest.TestCase):
    def test_gemini_legacy_male_voice_migrates_to_female_default(self):
        with mock.patch.object(config_manager, "load_api_keys", return_value={"voice_name": "Charon"}):
            self.assertEqual(config_manager.get_voice(), "Aoede")

    def test_edge_ignores_male_configured_voice(self):
        player = create_tts_player({"tts_engine": "edgetts", "tts_voice": "en-US-GuyNeural"})
        self.assertEqual(player._engine.voice, DEFAULT_EDGE_FEMALE_VOICE)

    def test_kokoro_ignores_non_allowlisted_voice(self):
        self.assertEqual(
            select_female_tts_voice("kokoro", "am_adam"),
            DEFAULT_KOKORO_FEMALE_VOICE,
        )

    def test_elevenlabs_ignores_male_configured_voice(self):
        player = create_tts_player({
            "tts_engine": "elevenlabs",
            "tts_voice": "pNInz6obpgDQGcFmaJgB",
            "elevenlabs_api_key": "test",
        })
        self.assertEqual(player._engine.voice_id, DEFAULT_ELEVENLABS_FEMALE_VOICE_ID)


class DpiStartupTests(unittest.TestCase):
    def test_existing_windows_context_disables_only_qt_setter(self):
        with mock.patch("core.windows_dpi.process_already_dpi_aware", return_value=True):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertTrue(configure_qt_dpi_startup())
                self.assertEqual(os.environ["QT_QPA_PLATFORM"], "windows:dpiawareness=0")

    def test_explicit_qt_platform_is_preserved(self):
        with mock.patch("core.windows_dpi.process_already_dpi_aware", return_value=True):
            with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=True):
                self.assertFalse(configure_qt_dpi_startup())
                self.assertEqual(os.environ["QT_QPA_PLATFORM"], "offscreen")


if __name__ == "__main__":
    unittest.main()
