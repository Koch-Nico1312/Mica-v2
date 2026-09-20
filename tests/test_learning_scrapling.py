from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "mica_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from services.common.learning import (
    SafeWebClient,
    scrapling_fetch_page,
    scrapling_search,
    scrapling_wanted,
)

BODY_TEXT = (
    "Erste Zeile mit ausreichend Inhalt fuer die Mindestlaenge.\n\n\n\n"
    "Zweite Zeile mit noch mehr Inhalt fuer den Test der Normalisierung."
)


class _FakeResponse:
    """Minimal stand-in for a Scrapling Response object."""

    def __init__(
        self,
        status: int = 200,
        headers: dict | None = None,
        body: bytes = b"",
        url: str = "",
        text: str | None = None,
        elements: list | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.url = url
        self.html_content = body.decode("utf-8", errors="replace")
        self._text = text
        self._elements = elements or []

    def get_all_text(self) -> str:
        return self._text if self._text is not None else self.html_content

    def css(self, selector: str, **kwargs) -> list:
        return self._elements


class _FakeElement:
    def __init__(self, href: str, text: str) -> None:
        self.attrib = {"href": href}
        self.text = text


class _FakeFetcher:
    """Records every call so the tests can assert on the guard behaviour."""

    calls: list[tuple[str, dict]] = []
    responses: list[_FakeResponse] = []
    configured: list[dict] = []
    adaptive = False

    @classmethod
    def reset(cls, responses: list[_FakeResponse]) -> None:
        cls.calls = []
        cls.responses = list(responses)
        cls.configured = []
        cls.adaptive = False

    @classmethod
    def configure(cls, **kwargs) -> None:
        cls.configured.append(kwargs)

    @classmethod
    def get(cls, url: str, **kwargs) -> _FakeResponse:
        cls.calls.append((url, kwargs))
        if not cls.responses:
            raise AssertionError("fake Scrapling received an unexpected request")
        return cls.responses.pop(0)


class ScraplingLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(self._uninstall)
        self._install()
        # Public-IP resolution needs DNS; the guard itself is covered by
        # test_host_filter_is_shared_with_the_httpx_path.
        patcher = mock.patch.object(SafeWebClient, "_public_host", staticmethod(lambda host: True))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _uninstall(self) -> None:
        for name in ("scrapling", "scrapling.fetchers"):
            sys.modules.pop(name, None)

    def _install(self, responses: list[_FakeResponse] | None = None) -> None:
        _FakeFetcher.reset(responses or [])
        package = types.ModuleType("scrapling")
        fetchers = types.ModuleType("scrapling.fetchers")
        fetchers.Fetcher = _FakeFetcher
        package.fetchers = fetchers
        sys.modules["scrapling"] = package
        sys.modules["scrapling.fetchers"] = fetchers

    # ── fetch: guards ────────────────────────────────────────────────────────

    def test_fetch_returns_normalized_text_from_the_validated_url(self) -> None:
        self._install([_FakeResponse(body=BODY_TEXT.encode(), url="https://docs.python.org/3/")])
        result = scrapling_fetch_page("https://docs.python.org/3/", ["docs.python.org"])
        self.assertEqual(result["url"], "https://docs.python.org/3/")
        self.assertNotIn("\n\n\n", result["text"])
        self.assertIn("Erste Zeile", result["text"])
        # Redirects are resolved by us, never delegated to Scrapling.
        self.assertEqual(_FakeFetcher.calls[0][1]["follow_redirects"], False)
        self.assertEqual(_FakeFetcher.configured, [{"adaptive": True}])

    def test_fetch_walks_redirect_hops_and_revalidates_every_one(self) -> None:
        self._install([
            _FakeResponse(status=302, headers={"Location": "/moved"}, url="https://docs.python.org/start"),
            _FakeResponse(status=301, headers={"location": "https://docs.python.org/final"}, url="https://docs.python.org/moved"),
            _FakeResponse(body=BODY_TEXT.encode(), url="https://docs.python.org/final"),
        ])
        result = scrapling_fetch_page("https://docs.python.org/start", ["docs.python.org"])
        self.assertEqual(result["url"], "https://docs.python.org/final")
        self.assertEqual(
            [url for url, _ in _FakeFetcher.calls],
            ["https://docs.python.org/start", "https://docs.python.org/moved", "https://docs.python.org/final"],
        )

    def test_fetch_refuses_a_redirect_that_leaves_the_allowlist(self) -> None:
        self._install([
            _FakeResponse(status=302, headers={"Location": "https://evil.example.com/steal"}, url="https://docs.python.org/start"),
        ])
        with self.assertRaises(ValueError):
            scrapling_fetch_page("https://docs.python.org/start", ["docs.python.org"])
        # The off-allowlist hop must never be requested.
        self.assertEqual(len(_FakeFetcher.calls), 1)

    def test_fetch_refuses_a_redirect_without_location(self) -> None:
        self._install([_FakeResponse(status=302, url="https://docs.python.org/start")])
        with self.assertRaises(ValueError):
            scrapling_fetch_page("https://docs.python.org/start", ["docs.python.org"])

    def test_fetch_stops_after_max_redirects(self) -> None:
        self._install([
            _FakeResponse(status=302, headers={"Location": "/loop"}, url="https://docs.python.org/loop")
            for _ in range(SafeWebClient.MAX_REDIRECTS + 2)
        ])
        with self.assertRaisesRegex(ValueError, "Too many redirects"):
            scrapling_fetch_page("https://docs.python.org/loop", ["docs.python.org"])

    def test_fetch_rejects_a_body_above_the_size_limit(self) -> None:
        oversized = b"x" * (SafeWebClient.MAX_BYTES + 1)
        self._install([_FakeResponse(body=oversized, url="https://docs.python.org/3/")])
        with self.assertRaisesRegex(ValueError, "size limit"):
            scrapling_fetch_page("https://docs.python.org/3/", ["docs.python.org"])

    def test_fetch_rejects_content_served_from_an_unvalidated_url(self) -> None:
        # Simulates a Scrapling version that follows redirects despite the flag:
        # the URL that actually served the body still has to pass the guards.
        self._install([_FakeResponse(body=BODY_TEXT.encode(), url="https://evil.example.com/x")])
        with self.assertRaises(ValueError):
            scrapling_fetch_page("https://docs.python.org/3/", ["docs.python.org"])

    def test_fetch_rejects_error_statuses_binary_types_and_thin_pages(self) -> None:
        cases = [
            (_FakeResponse(status=404, url="https://docs.python.org/x"), "HTTP 404"),
            (_FakeResponse(body=b"pdf", headers={"content-type": "application/pdf"}, url="https://docs.python.org/x"), "content type"),
            (_FakeResponse(body=b"short", url="https://docs.python.org/x"), "too little readable text"),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                self._install([response])
                with self.assertRaisesRegex(ValueError, expected):
                    scrapling_fetch_page("https://docs.python.org/x", ["docs.python.org"])

    # ── search ───────────────────────────────────────────────────────────────

    def test_search_relocates_saved_locators_and_filters_hosts(self) -> None:
        self._install([_FakeResponse(elements=[_FakeElement("https://docs.python.org/3/library/asyncio.html", "Asyncio")])])
        results = scrapling_search("asyncio", ["docs.python.org"], 3)
        self.assertEqual(results, [{"title": "Asyncio", "url": "https://docs.python.org/3/library/asyncio.html", "snippet": ""}])

    def test_search_validates_links_against_the_allowlist(self) -> None:
        self._install([_FakeResponse(elements=[
            _FakeElement("https://evil.example.com/phish", "Phish"),
            _FakeElement("https://docs.python.org/3/", "Docs"),
        ])])
        results = scrapling_search("asyncio", ["docs.python.org"], 3)
        self.assertEqual([item["url"] for item in results], ["https://docs.python.org/3/"])

    def test_search_falls_back_to_recording_locators(self) -> None:
        # Empty adaptive result on both search engines -> record instead.
        self._install([_FakeResponse(elements=[]), _FakeResponse(elements=[])])
        scrapling_search("asyncio", ["docs.python.org"], 3)
        self.assertEqual(_FakeFetcher.configured, [{"adaptive": True}])

    # ── shared host filter ───────────────────────────────────────────────────

    def test_host_filter_is_shared_with_the_httpx_path(self) -> None:
        client = SafeWebClient()
        self.assertTrue(client._allowed_host("docs.python.org", ["docs.python.org"]))
        self.assertTrue(client._allowed_host("sub.docs.python.org", ["docs.python.org"]))
        self.assertFalse(client._allowed_host("evil.example.com", ["docs.python.org"]))
        # Suffix confusion must not pass: notdocs.python.org is a different host.
        self.assertFalse(client._allowed_host("notdocs.python.org", ["docs.python.org"]))
        with self.assertRaises(ValueError):
            client.validate_url("http://docs.python.org/insecure", ["docs.python.org"])
        with self.assertRaises(ValueError):
            client.validate_url("https://user:pass@docs.python.org/x", ["docs.python.org"])
        with self.assertRaises(ValueError):
            client.validate_url("https://docs.python.org:8443/x", ["docs.python.org"])

    # ── optional dependency handling ─────────────────────────────────────────

    def test_layer_is_disabled_by_the_env_flag(self) -> None:
        with mock.patch.dict(os.environ, {"MICA_SCRAPLING_ENABLED": "0"}):
            self.assertFalse(scrapling_wanted())
        with mock.patch.dict(os.environ, {"MICA_SCRAPLING_ENABLED": "1"}):
            self.assertTrue(scrapling_wanted())

    def test_helpers_fail_soft_when_the_package_is_missing(self) -> None:
        with mock.patch.dict(sys.modules, {"scrapling": None, "scrapling.fetchers": None}):
            self.assertFalse(scrapling_wanted())
            with self.assertRaises(Exception):
                scrapling_search("asyncio", ["docs.python.org"], 3)
            with self.assertRaises(Exception):
                scrapling_fetch_page("https://docs.python.org/3/", ["docs.python.org"])


if __name__ == "__main__":
    unittest.main()
