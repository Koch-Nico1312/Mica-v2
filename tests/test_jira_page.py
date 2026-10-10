"""Offscreen UI tests: no automatic external query, safe async completion."""
import os
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication

from desktop.jira_page import JiraPage


def test_ui_connection_search_and_stale_site_clearing():
    app = QApplication.instance() or QApplication([])
    calls = []
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def resources(self):
            calls.append('resources')
            return [{'id': 'site', 'name': 'Team'}]
        def search(self, site, query):
            calls.append((site, query))
            return {'content': [{'type': 'text', 'text': '<b>Remote text stays plain</b>'}]}
    with patch('desktop.jira_page.get_secret', return_value='nico@example.com'):
        page = JiraPage(client_factory=Client)
    assert calls == []
    assert not page.search_button.isEnabled()
    page.connect_button.click()
    deadline = time.monotonic() + 3
    while page.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert not page.busy and page.search_button.isEnabled()
    assert page.sites.currentData() == 'site'
    page.search_button.click()
    deadline = time.monotonic() + 3
    while page.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert not page.busy
    assert page.report.toPlainText() == '<b>Remote text stays plain</b>'
    page.sites.clear()
    page._receive('resources', None, 'Access denied')
    assert not page.search_button.isEnabled()
    page.close()
