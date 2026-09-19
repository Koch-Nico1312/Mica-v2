from __future__ import annotations

import unittest
from datetime import date, timedelta

from tests.manual_everyday_acceptance import ALL_MODES, _summary


class EverydayAcceptanceTests(unittest.TestCase):
    def test_seven_safe_days_and_three_full_days_are_required(self):
        today = date(2026, 9, 17)
        records = []
        for offset in range(7):
            full = offset < 3
            records.append({
                "day": str(today - timedelta(days=6 - offset)),
                "persona_correct": True, "profile_correct": True, "profile_private": True,
                "no_data_loss": True, "no_unauthorized_action": True, "no_critical_defect": True,
                "text_used": full, "voice_used": full, "restart_completed": full,
                "modes": sorted(ALL_MODES) if full else [],
            })
        result = _summary(records, today)
        self.assertTrue(result["phase0_seven_safe_days_passed"])
        self.assertTrue(result["phase1_three_full_days_passed"])

    def test_gap_or_defect_prevents_acceptance(self):
        today = date(2026, 9, 17)
        records = [{
            "day": str(today), "persona_correct": True, "profile_correct": True,
            "profile_private": True, "no_data_loss": True,
            "no_unauthorized_action": True, "no_critical_defect": False,
            "text_used": True, "voice_used": True, "restart_completed": True,
            "modes": sorted(ALL_MODES),
        }]
        result = _summary(records, today)
        self.assertFalse(result["phase0_seven_safe_days_passed"])
        self.assertFalse(result["phase1_three_full_days_passed"])


if __name__ == "__main__":
    unittest.main()
