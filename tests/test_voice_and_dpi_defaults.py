import os
import unittest
from unittest import mock

from desktop.core.windows_dpi import configure_qt_dpi_startup
from desktop.memory import config_manager




class DpiStartupTests(unittest.TestCase):
    def test_existing_windows_context_disables_only_qt_setter(self):
        with mock.patch("desktop.core.windows_dpi.process_already_dpi_aware", return_value=True):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertTrue(configure_qt_dpi_startup())
                self.assertEqual(os.environ["QT_QPA_PLATFORM"], "windows:dpiawareness=0")

    def test_explicit_qt_platform_is_preserved(self):
        with mock.patch("desktop.core.windows_dpi.process_already_dpi_aware", return_value=True):
            with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=True):
                self.assertFalse(configure_qt_dpi_startup())
                self.assertEqual(os.environ["QT_QPA_PLATFORM"], "offscreen")


if __name__ == "__main__":
    unittest.main()
