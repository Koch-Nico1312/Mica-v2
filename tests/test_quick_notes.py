import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QMessageBox
from desktop.core.quick_notes import MAX_BODY, QuickNotesStore, search_notes
from desktop.quick_notes_page import QuickNotesPage


def test_save_update_search_restart_and_stale_writer(tmp_path):
    store = QuickNotesStore(tmp_path / 'notes.json')
    assert store.read()['notes'] == [] and not store.path.exists()
    data, identifier = store.change('save', revision=0, title=' Idee ', body='MICA\nWörtlich: .*')
    stale = data['revision']
    data, same_id = store.change('save', revision=stale, note_id=identifier, title='Idee', body='Überarbeitet')
    assert same_id == identifier and len(data['notes']) == 1
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match='inzwischen'):
        store.change('save', revision=stale, note_id=identifier, title='Andere', body='Veraltet')
    assert store.path.read_bytes() == before
    assert QuickNotesStore(store.path).read() == data
    assert search_notes(data['notes'], 'überARBEITET') == data['notes']
    assert search_notes(data['notes'], '.*') == []
    data, _ = store.change('remove', revision=data['revision'], note_id=identifier)
    assert data['notes'] == [] and store.read() == data


@pytest.mark.parametrize('title,body', [('', 'Text'), ('Zeile\nZwei', 'Text'),
                                     ('x' * 81, 'Text'), ('Titel', ' '), ('Titel', 'x' * (MAX_BODY + 1))])
def test_invalid_notes_never_write(tmp_path, title, body):
    store = QuickNotesStore(tmp_path / 'notes.json')
    with pytest.raises(ValueError):
        store.change('save', revision=0, title=title, body=body)
    assert not store.path.exists()


def test_storage_failure_and_corruption_preserve_existing_file(tmp_path):
    store = QuickNotesStore(tmp_path / 'notes.json')
    data, identifier = store.change('save', revision=0, title='Idee', body='Alt')
    before = store.path.read_bytes()
    with patch('desktop.core.local_state.os.replace', side_effect=PermissionError('locked')):
        with pytest.raises(PermissionError):
            store.change('save', revision=1, note_id=identifier, title='Idee', body='Neu')
    assert store.path.read_bytes() == before
    assert {path.name for path in tmp_path.iterdir()} == {'notes.json', 'notes.json.lock'}
    data['notes'].append(data['notes'][0].copy())
    store.path.write_text(json.dumps(data), encoding='utf-8')
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.change('save', revision=1, title='Neue', body='Text')
    assert store.path.read_bytes() == before


def test_ui_privacy_save_filter_and_protected_draft(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = QuickNotesStore(tmp_path / 'notes.json')
    privacy = {'save': False}
    page = QuickNotesPage(store=store, can_save=lambda: privacy['save'])
    page.title.setText('Idee')
    page.body.setPlainText('Einkauf planen')
    page.save_button.click()
    assert not store.path.exists() and page.dirty() and 'Speicherung' in page.status.text()
    privacy['save'] = True
    page.save_button.click()
    assert not page.dirty() and len(store.read()['notes']) == 1
    page.new_button.click()
    page.title.setText('Projekt')
    page.body.setPlainText('Nächster Schritt')
    page.save_button.click()
    page.body.setPlainText('Ungespeicherter Entwurf')
    page.search.setText('Idee')
    assert page.notes.count() == 1 and page.body.toPlainText() == 'Ungespeicherter Entwurf'
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        page.notes.setCurrentRow(0)
        page.reload()
        page.new_note()
    assert page.title.text() == 'Projekt' and page.dirty()
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        page.notes.setCurrentRow(0)
    assert page.title.text() == 'Idee' and not page.dirty()
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        page.remove()
    assert len(store.read()['notes']) == 2
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        page.remove()
    assert len(store.read()['notes']) == 1 and page.title.text() == ''
    page.close()
    app.processEvents()


def test_ui_stale_save_keeps_draft_and_storage_failure_keeps_editor(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = QuickNotesStore(tmp_path / 'notes.json')
    page = QuickNotesPage(store=store)
    page.title.setText('Meine Idee')
    page.body.setPlainText('Mein Entwurf')
    store.change('save', revision=0, title='Andere Instanz', body='Text')
    page.save()
    assert page.body.toPlainText() == 'Mein Entwurf' and 'inzwischen' in page.status.text()
    assert len(store.read()['notes']) == 1
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        page.reload()
    page.title.setText('Meine Idee')
    page.body.setPlainText('Mein Entwurf')
    with patch('desktop.core.local_state.os.replace', side_effect=PermissionError('locked')):
        page.save()
    assert page.dirty() and page.body.toPlainText() == 'Mein Entwurf'
    page.save()
    assert len(store.read()['notes']) == 2 and not page.dirty()
    page.close()
    app.processEvents()


def test_note_count_limit_preserves_state_and_edits_remain_possible(tmp_path):
    store = QuickNotesStore(tmp_path / 'notes.json')
    data, identifier = store.change('save', revision=0, title='Erste', body='Text')
    data['notes'] = [dict(data['notes'][0], id=f'{index:032x}') for index in range(100)]
    store.path.write_text(json.dumps(data), encoding='utf-8')
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match='100'):
        store.change('save', revision=1, title='Zu viele', body='Text')
    assert store.path.read_bytes() == before
    data, _ = store.change('save', revision=1, note_id=data['notes'][0]['id'], title='Erste', body='Bearbeitet')
    assert len(data['notes']) == 100 and data['notes'][0]['body'] == 'Bearbeitet'
