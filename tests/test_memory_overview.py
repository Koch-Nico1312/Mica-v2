from __future__ import annotations

import os
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QMessageBox

from backend.services.api.routers.memory import MemoryRoutes
from desktop.control_center import BackendMemoryPage, memory_certainty

APP = QApplication.instance() or QApplication([])


def entry(identifier='one', **updates):
    return {'id': identifier, 'title': 'Projekt MICA', 'body': 'Lokaler Assistent',
            'source': 'desktop_user', 'kind': 'memory', 'explicitly_remembered': True,
            'created_at': '2026-10-03T08:00:00+00:00', 'updated_at': '',
            'sources': [], **updates}


@pytest.fixture
def view():
    page = BackendMemoryPage()
    page.resize(880, 720)
    page.show()
    APP.processEvents()
    yield page
    page._auth_timer.stop()
    page.close()
    page.deleteLater()
    APP.processEvents()


def load(page, items):
    page._received('memory', {'items': items}, '')


def unlock(page):
    page._received('auth', {}, '')


def test_api_exposes_explicit_provenance_without_promoting_unknown_sources():
    routes = MemoryRoutes()
    routes.brain = Mock()
    routes.brain.documents.return_value = [entry(), entry('two', explicitly_remembered='false', inferred=True)]
    items = routes.memory_items()['items']
    assert items[0]['explicitly_remembered'] is True
    assert items[0]['confirmed'] is False
    assert items[1]['explicitly_remembered'] is False
    assert items[1]['inferred'] is True
    assert items[1]['body'] == 'Lokaler Assistent'


def test_inference_marker_takes_priority_over_confirmation():
    assert memory_certainty(entry(inferred=True, confirmed=True))[0] == 'inferred'
    assert memory_certainty(entry(kind='reflections'))[0] == 'inferred'
    assert memory_certainty(entry(explicitly_remembered=False))[0] == 'unconfirmed'
    assert memory_certainty(entry(explicitly_remembered=False, confirmed=True))[0] == 'confirmed'


def test_provenance_and_actual_update_date_are_visible(view):
    load(view, [entry(updated_at='2026-10-04T10:00:00+00:00', sources=['https://example.org/source'])])
    view.table.selectRow(0)
    assert view.table.item(0, 2).text() == 'Von dir gespeichert'
    assert view.table.item(0, 3).text() == '04.10. 12:00'
    assert 'https://example.org/source' in view.metadata.toPlainText()
    assert 'Direkt von dir gespeichert' in view.metadata.toPlainText()
    assert view.title.isReadOnly()


def test_new_draft_survives_refresh(view):
    view.title.setText('Neue Notiz')
    view.body.setPlainText('Offener Entwurf')
    load(view, [entry()])
    assert view.selected() is None
    assert view.title.text() == 'Neue Notiz'
    assert view.body.toPlainText() == 'Offener Entwurf'


def test_existing_long_title_is_not_truncated_or_marked_dirty(view):
    title = 'Langer gespeicherter Titel ' * 10
    load(view, [entry(title=title)])
    view.table.selectRow(0)
    assert view.title.text() == title
    assert not view._dirty()
    view.new_entry()
    assert view.title.maxLength() == 160


def test_dirty_editor_survives_row_reordering_and_search(view):
    load(view, [entry(), entry('two', title='Anderes Thema')])
    unlock(view)
    view.table.selectRow(0)
    view.body.setPlainText('Korrigierter Entwurf')
    load(view, [entry('two', title='Anderes Thema'), entry()])
    assert view.selected()['id'] == 'one'
    assert view.table.currentRow() == 1
    assert view.body.toPlainText() == 'Korrigierter Entwurf'
    view.search.setText('Anderes Thema')
    assert view.table.currentRow() == -1
    assert view.selected()['id'] == 'one'
    client = Mock()
    with patch.object(view, '_run', side_effect=lambda kind, action: action(client)):
        view.correct()
    client.correct_memory.assert_called_once_with('one', 'Korrigierter Entwurf')


def test_switching_items_requires_explicit_draft_discard(view):
    load(view, [entry(), entry('two', title='Andere Notiz', body='Zweiter Inhalt')])
    view.table.selectRow(0)
    view.body.setPlainText('Nicht gespeichert')
    with patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        view.table.selectRow(1)
    assert view.selected()['id'] == 'one'
    assert view.table.currentRow() == 0
    assert view.body.toPlainText() == 'Nicht gespeichert'
    with patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        view.table.selectRow(1)
    assert view.selected()['id'] == 'two'
    assert view.body.toPlainText() == 'Zweiter Inhalt'


def test_remote_change_keeps_draft_and_blocks_overwrite_until_reload(view):
    load(view, [entry()])
    unlock(view)
    view.table.selectRow(0)
    view.body.setPlainText('Mein Entwurf')
    load(view, [entry(body='Neue gespeicherte Version', updated_at='2026-10-04T11:00:00+00:00')])
    assert view.body.toPlainText() == 'Mein Entwurf'
    assert not view.correct_button.isEnabled()
    assert not view.forget_button.isEnabled()
    assert 'geändert oder gelöscht' in view.metadata.toPlainText()
    with patch.object(view, '_run') as run:
        view.correct()
    run.assert_not_called()
    with patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        view.reload_entry()
    assert view.body.toPlainText() == 'Neue gespeicherte Version'
    assert not view._conflict


def test_deleted_remote_item_does_not_rebind_editor_to_another_row(view):
    load(view, [entry(), entry('two')])
    unlock(view)
    view.table.selectRow(0)
    load(view, [entry('two')])
    assert view.selected()['id'] == 'one'
    assert not view.forget_button.isEnabled()
    assert not view.correct_button.isEnabled()
    assert view.table.currentRow() == -1


def test_failed_load_and_expired_unlock_preserve_edits(view):
    load(view, [entry()])
    unlock(view)
    view.table.selectRow(0)
    view.body.setPlainText('Entwurf')
    view._received('memory', None, 'Connection lost')
    assert view.body.toPlainText() == 'Entwurf'
    assert not view.correct_button.isEnabled()
    load(view, [entry()])
    assert view.correct_button.isEnabled()
    view._lock_editing()
    assert view.body.toPlainText() == 'Entwurf'
    assert not view.correct_button.isEnabled()


def test_certainty_filter_never_treats_inference_as_user_fact(view):
    load(view, [entry(), entry('two', inferred=True)])
    view.certainty_filter.setCurrentIndex(view.certainty_filter.findData('inferred'))
    assert [item['id'] for item in view._items] == ['two']
    view.certainty_filter.setCurrentIndex(view.certainty_filter.findData('explicit'))
    assert [item['id'] for item in view._items] == ['one']


def test_delete_confirmation_and_request_remain_bound_to_editor_id(view):
    load(view, [entry(), entry('two')])
    unlock(view)
    view.table.selectRow(0)
    client = Mock()
    with patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.No), \
            patch.object(view, '_run') as run:
        view.forget()
    run.assert_not_called()
    with patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
            patch.object(view, '_run', side_effect=lambda kind, action: action(client)):
        view.forget()
    client.forget_memory.assert_called_once_with('one')


def test_successful_creation_binds_returned_document_before_refresh(view):
    load(view, [])
    unlock(view)
    view.title.setText('Neue Notiz')
    view.body.setPlainText('Mein Inhalt')
    view._save_operation = 'create'
    with patch.object(view, 'refresh') as refresh:
        view._received('saved', {'document': {'id': 'new', 'created_at': '2026-10-04T10:00:00+00:00'}}, '')
    refresh.assert_called_once()
    assert view.selected()['id'] == 'new'
    assert not view._dirty()
    load(view, [entry('new', title='Neue Notiz', body='Mein Inhalt')])
    assert view.body.toPlainText() == 'Mein Inhalt'
    assert not view.correct_button.isEnabled()


def test_successful_correction_keeps_inference_classification(view):
    original = entry(inferred=True)
    load(view, [original])
    unlock(view)
    view.table.selectRow(0)
    view.body.setPlainText('Korrigierte Vermutung')
    corrected = {**original, 'body': 'Korrigierte Vermutung', 'updated_at': '2026-10-04T10:00:00+00:00'}
    view._save_operation = 'correct'
    with patch.object(view, 'refresh'):
        view._received('saved', {'document': corrected}, '')
    load(view, [corrected])
    assert not view._dirty()
    assert memory_certainty(view.selected())[0] == 'inferred'
    assert not view._conflict


def test_delete_success_resets_editor_but_failure_retains_draft(view):
    load(view, [entry()])
    unlock(view)
    view.table.selectRow(0)
    view.body.setPlainText('Entwurf')
    view._save_operation = 'forget'
    view._received('saved', None, 'Backend unavailable')
    assert view.selected()['id'] == 'one'
    assert view.body.toPlainText() == 'Entwurf'
    assert not view.forget_button.isEnabled()
    with patch.object(view, 'refresh'):
        view._received('saved', {'deleted': True}, '')
    assert view.selected() is None
    assert view.body.toPlainText() == ''
    assert not view._dirty()
