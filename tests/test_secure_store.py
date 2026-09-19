from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import secure_store


class SecureStoreTests(unittest.TestCase):
    def test_rejects_invalid_names_and_empty_values_before_backend_write(self):
        with self.assertRaises(ValueError):
            secure_store._valid_name("../../token")
        with self.assertRaises(ValueError):
            secure_store.set_secret("VALID_NAME", "")

    def test_accepts_only_windows_credential_manager_backend(self):
        NullBackend = type("NullBackend", (), {})
        NullBackend.__module__ = "keyring.backends.null"
        fake = SimpleNamespace(get_keyring=lambda: NullBackend())
        with patch.object(secure_store.os, "name", "nt"), patch.dict("sys.modules", {"keyring": fake}):
            with self.assertRaisesRegex(secure_store.SecureStoreUnavailable, "not Windows"):
                secure_store._backend()


if __name__ == "__main__":
    unittest.main(verbosity=2)
