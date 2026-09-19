from __future__ import annotations

import unittest

from core.hardware_recommendation import provider_recommendation


class HardwareRecommendationTests(unittest.TestCase):
    def test_weak_local_hardware_recommends_gemini_without_switching(self):
        result = provider_recommendation(
            cpu_logical=2, memory_bytes=8 * 1024**3, configured_provider="ollama",
        )
        self.assertEqual(result["recommended_provider"], "gemini")
        self.assertEqual(result["recommended_voice"], "gemini_tts")
        self.assertTrue(result["requires_explicit_opt_in"])
        self.assertTrue(result["sends_reply_text_to_cloud"])

    def test_adequate_hardware_and_explicit_cloud_need_no_suggestion(self):
        self.assertIsNone(provider_recommendation(
            cpu_logical=8, memory_bytes=32 * 1024**3, configured_provider="ollama",
        ))
        self.assertIsNone(provider_recommendation(
            cpu_logical=2, memory_bytes=8 * 1024**3, configured_provider="openai_api",
        ))


if __name__ == "__main__":
    unittest.main()
