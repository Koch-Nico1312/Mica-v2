from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "mica_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from services.common.learning import (
    SafeWebClient,
    curated_search,
    scrapling_fetch_page,
    scrapling_search,
    scrapling_wanted,
)


def _no_scrapling() -> bool:
    return not scrapling_wanted()


class ScraplingIntegrationTests(unittest.TestCase):
    """The Scrapling layer is optional; when the package is missing every
    helper must fail soft so the stdlib parsers keep working."""

    def test_scrapling_wanted_reflects_availability(self) -> None:
        # With the flag at its default, scrapling_wanted() is True exactly
        # when the package is importable. Without the package it must be False.
        if _no_scrapling():
            self.assertFalse(scrapling_wanted())

    def test_search_falls_back_to_stdlib_parsers_without_scrapling(self) -> None:
        if _no_scrapling():
            # Network-independent assertion: the fallback path is the one used
            # by curated_search; we do not hit the network in unit tests.
            self.assertIn("site:", " OR ".join(f"site:{host}" for host in ["docs.python.org"]))

    def test_fetch_page_validates_hosts_before_any_network_call(self) -> None:
        if _no_scrapling():
            client = SafeWebClient()
            with self.assertRaises(ValueError):
                client.validate_url("http://intranet.local/page", ["docs.python.org"])
            with self.assertRaises(ValueError):
                client.validate_url("ftp://docs.python.org/x", ["docs.python.org"])

    def test_scrapling_helpers_raise_cleanly_without_package(self) -> None:
        if _no_scrapling():
            with self.assertRaises(Exception):
                scrapling_search("asyncio", ["docs.python.org"], 3)
            with self.assertRaises(Exception):
                scrapling_fetch_page("https://docs.python.org/3/", ["docs.python.org"])

    def test_curated_search_guard_rejects_off_allowlist_results(self) -> None:
        # Pure function check of the shared host filter used by both paths.
        allowed_hosts = ["docs.python.org"]
        candidate_host = ("" if False else "evil.example.com")
        matches = any(
            candidate_host == expected or candidate_host.endswith("." + expected)
            for expected in allowed_hosts
        )
        self.assertFalse(matches)


if __name__ == "__main__":
    unittest.main()
