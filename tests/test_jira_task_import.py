import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QMessageBox
from desktop.core.jira_task_import import issue_task_draft
from desktop.core.offline_tasks import OfflineTasks
from desktop.jira_page import JiraPage


def issue_result(key='MICA-123'):
    return {'content': [{'type': 'text', 'text': json.dumps({'key': key, 'fields': {
        'summary': 'Fehler prüfen', 'description': {'type': 'doc', 'content': [
            {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Konkreter Hinweis.'}]}]},
        'duedate': '2026-10-12', 'status': {'name': 'Done'}}})}]}


def test_import_is_explicit_open_draft_with_stable_site_specific_identity():
    draft = issue_task_draft(issue_result(), 'site', 'mica-123')
    assert draft['title'] == 'MICA-123: Fehler prüfen'
    assert 'Konkreter Hinweis.' in draft['description']
    assert draft['status'] == 'open' and draft['due_at'] is None
    assert draft['id'] == issue_task_draft(issue_result(), 'site', 'MICA-123')['id']
    assert draft['id'] != issue_task_draft(issue_result(), 'other-site', 'MICA-123')['id']
    with pytest.raises(ValueError):
        issue_task_draft(issue_result('OTHER-1'), 'site', 'MICA-123')


def test_duplicate_import_never_overwrites_local_edits_and_survives_restart(tmp_path):
    path = tmp_path / 'tasks.json'
    store = OfflineTasks(path)
    draft = issue_task_draft(issue_result(), 'site', 'MICA-123')
    store.stage(draft, create_only=True)
    store.stage({**draft, 'title': 'Meine geänderte Aufgabe'})
    reopened = OfflineTasks(path)
    with pytest.raises(ValueError, match='bereits'):
        reopened.stage(draft, create_only=True)
    assert reopened.view()[0]['title'] == 'Meine geänderte Aufgabe'
    assert len(reopened.read()['pending']) == 1


def test_ui_import_confirmation_cancel_privacy_and_stale_inputs(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = OfflineTasks(tmp_path / 'tasks.json')
    with patch('desktop.jira_page.get_secret', return_value=None):
        page = JiraPage(task_store=store)
    page.sites.addItem('Team', 'site')
    page.sites.setCurrentIndex(0)
    page.issue_key.setText('MICA-123')
    page._issue_context = ('site', 'MICA-123')
    page._receive('issue', issue_result(), '')
    assert page.import_button.isEnabled()
    with patch('desktop.jira_page.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        page.import_button.click()
    assert store.read()['pending'] == []
    page.can_save = lambda: False
    with patch('desktop.jira_page.QMessageBox.question') as question:
        page.import_button.click()
    question.assert_not_called()
    assert store.read()['pending'] == []
    page.can_save = lambda: True
    with patch('desktop.jira_page.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        page.import_button.click()
    assert len(store.read()['pending']) == 1
    assert not page.import_button.isEnabled()
    page._receive('issue', issue_result(), '')
    assert page.import_button.isEnabled()
    page.issue_key.setText('MICA-999')
    assert not page.import_button.isEnabled()
    page.close()
    app.processEvents()
