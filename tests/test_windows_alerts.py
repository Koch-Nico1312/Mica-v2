from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from core import windows_alerts


class WindowsAlertTests(unittest.TestCase):
    def test_non_windows_is_a_safe_noop(self):
        with patch.object(windows_alerts.os, "name", "posix"):
            self.assertFalse(windows_alerts.notify_critical("failure"))

    def test_windows_notification_contains_only_sanitized_error_class(self):
        notifier = MagicMock()
        module = SimpleNamespace(ToastNotifier=lambda: notifier)
        with (
            patch.object(windows_alerts.os, "name", "nt"),
            patch.dict("sys.modules", {"win10toast": module}),
            patch.object(windows_alerts.threading, "Thread") as thread,
        ):
            self.assertTrue(windows_alerts.notify_critical("timeout SECRET text"))
            target = thread.call_args.kwargs["target"]
            target()
            message = notifier.show_toast.call_args.args[1]
            self.assertIn("timeoutSECRETtext", message)
            self.assertNotIn(" SECRET ", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
