from __future__ import annotations

import unittest

from tests.manual_voice_acceptance import SENTENCES, _word_error_rate


class ManualVoiceAcceptanceTests(unittest.TestCase):
    def test_twenty_fixed_sentences_and_word_error_rate(self):
        self.assertEqual(len(SENTENCES), 20)
        self.assertEqual(_word_error_rate("Hallo Mica", "Hallo Mica"), 0.0)
        self.assertEqual(_word_error_rate("eins zwei drei", "eins zwei"), 1 / 3)


if __name__ == "__main__":
    unittest.main()
