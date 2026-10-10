import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QMessageBox
from desktop.core.quick_notes import MAX_BODY, QuickNotesStore, note_excerpt, search_notes
from desktop.quick_notes_page import QuickNotesPage
from desktop.core.checklists import ChecklistStore


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
    assert search_notes(data['notes'], '') == [] and store.read() == data
    assert data['notes'][0]['trashed']


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
    assert len(search_notes(store.read()['notes'], '')) == 1 and page.title.text() == ''
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


def test_pin_existing_format_restart_stale_write_and_bad_flag(tmp_path):
    store = QuickNotesStore(tmp_path / 'notes.json')
    data, first = store.change('save', revision=0, title='Alpha', body='Text')
    data, second = store.change('save', revision=1, title='Zebra', body='Text')
    assert 'pinned' not in data['notes'][1]
    data, _ = store.change('pin', revision=2, note_id=second, pinned=True)
    assert search_notes(data['notes'], '')[0]['id'] == second
    assert QuickNotesStore(store.path).read() == data
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match='inzwischen'):
        store.change('pin', revision=2, note_id=second, pinned=False)
    with pytest.raises(ValueError):
        store.change('pin', revision=3, note_id=second, pinned=1)
    assert store.path.read_bytes() == before
    data, _ = store.change('save', revision=3, note_id=second, title='Zebra', body='Bearbeitet')
    assert data['notes'][1]['pinned']
    data, _ = store.change('pin', revision=4, note_id=second, pinned=False)
    assert search_notes(data['notes'], '')[0]['id'] == first
    data['notes'][0]['pinned'] = 'true'
    store.path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        store.read()


def test_excerpt_includes_late_unicode_literal_hit_and_is_bounded():
    note = {'body': 'Erste Zeile\n' + 'x' * 500 + ' Straße ist hier ' + 'y' * 500}
    preview = note_excerpt(note, 'STRASSE')
    assert 'Straße' in preview and preview.startswith('…') and preview.endswith('…')
    assert len(preview) <= 142
    assert note_excerpt(note) == 'Erste Zeile'
    assert note_excerpt({'body': '<script> & .*'}, '.*') == '<script> & .*'


def test_ui_pin_preserves_draft_checks_privacy_and_keeps_identity(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = QuickNotesStore(tmp_path / 'notes.json')
    data, identifier = store.change('save', revision=0, title='Zebra', body='Gespeichert')
    store.change('save', revision=1, title='Alpha', body='Andere')
    privacy = {'save': True}
    page = QuickNotesPage(store=store, can_save=lambda: privacy['save'])
    page.notes.setCurrentRow(1)
    assert page.note_id == identifier
    page.body.setPlainText('Offener Entwurf')
    page.pin_button.click()
    assert page.notes.currentRow() == 0 and page.note_id == identifier
    assert page.body.toPlainText() == 'Offener Entwurf' and page.dirty()
    assert store.read()['notes'][0]['body'] == 'Gespeichert'
    assert 'Angeheftet' in page.notes.item(0).text()
    assert page.pin_button.text() == 'Notiz lösen'
    before = store.path.read_bytes()
    privacy['save'] = False
    page.pin_button.click()
    assert store.path.read_bytes() == before and page.dirty()
    privacy['save'] = True
    with patch('desktop.core.local_state.os.replace', side_effect=PermissionError):
        page.pin_button.click()
    assert store.path.read_bytes() == before and page.dirty()
    page.search.setText('Andere')
    assert page.notes.count() == 1 and page.body.toPlainText() == 'Offener Entwurf'
    assert page.result_count.text().startswith('1 / 2')
    page.close()
    app.processEvents()


def test_trash_restore_restart_and_purge_require_correct_state(tmp_path):
    store = QuickNotesStore(tmp_path / 'notes.json')
    data, identifier = store.change('save', revision=0, title='Idee', body='Text')
    data, _ = store.change('pin', revision=1, note_id=identifier, pinned=True)
    data, _ = store.change('remove', revision=2, note_id=identifier)
    assert search_notes(data['notes'], '') == []
    assert search_notes(data['notes'], '', trash_only=True)[0]['body'] == 'Text'
    assert QuickNotesStore(store.path).read() == data
    before = store.path.read_bytes()
    for operation, values in [('save', {'title': 'Neue', 'body': 'Text'}), ('pin', {'pinned': False}), ('remove', {})]:
        with pytest.raises(ValueError, match='wiederherstellen'):
            store.change(operation, revision=3, note_id=identifier, **values)
    with pytest.raises(ValueError, match='inzwischen'):
        store.change('restore', revision=2, note_id=identifier)
    assert store.path.read_bytes() == before
    data, _ = store.change('restore', revision=3, note_id=identifier)
    assert data['notes'][0]['pinned'] and search_notes(data['notes'], '')
    with pytest.raises(ValueError, match='Papierkorb'):
        store.change('purge', revision=4, note_id=identifier)
    data, _ = store.change('remove', revision=4, note_id=identifier)
    before = store.path.read_bytes()
    with patch('desktop.core.local_state.os.replace', side_effect=PermissionError), pytest.raises(PermissionError):
        store.change('purge', revision=5, note_id=identifier)
    assert store.path.read_bytes() == before
    data, _ = store.change('purge', revision=5, note_id=identifier)
    assert data['notes'] == []


def test_ui_trash_switch_draft_confirmation_restore_and_purge_privacy(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = QuickNotesStore(tmp_path / 'notes.json')
    store.change('save', revision=0, title='Idee', body='Text')
    privacy = {'save': True}
    page = QuickNotesPage(store=store, can_save=lambda: privacy['save'])
    page.notes.setCurrentRow(0)
    page.body.setPlainText('Entwurf')
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        page.trash.setChecked(True)
    assert not page.trash.isChecked() and page.body.toPlainText() == 'Entwurf'
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        page.remove()
    assert page.notes.count() == 0 and page.title.text() == ''
    page.trash.setChecked(True)
    page.notes.setCurrentRow(0)
    assert page.body.isReadOnly() and not page.save_button.isEnabled()
    assert page.body.toPlainText() == 'Text'
    before = store.path.read_bytes()
    privacy['save'] = False
    page.restore_button.click()
    assert store.path.read_bytes() == before
    privacy['save'] = True
    page.restore_button.click()
    assert page.notes.count() == 0
    page.trash.setChecked(False)
    page.notes.setCurrentRow(0)
    assert page.body.toPlainText() == 'Text' and not page.body.isReadOnly()
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        page.remove()
    page.trash.setChecked(True)
    page.notes.setCurrentRow(0)
    before = store.path.read_bytes()
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        page.remove()
    assert store.path.read_bytes() == before
    with patch('desktop.quick_notes_page.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        page.remove()
    assert store.read()['notes'] == [] and page.notes.count() == 0
    page.close()
    app.processEvents()


def test_note_to_list_confirmed_atomic_creation_preserves_unsaved_note(tmp_path):
    app = QApplication.instance() or QApplication([])
    notes = QuickNotesStore(tmp_path / 'notes.json')
    lists = ChecklistStore(tmp_path / 'lists.json')
    page = QuickNotesPage(store=notes, checklist_store=lists)
    page.title.setText('Einkauf')
    page.body.setPlainText('- Milch\n- [x] Brot')
    with patch('desktop.quick_notes_page.QMessageBox.exec', return_value=QMessageBox.StandardButton.No):
        page.list_button.click()
    assert not lists.path.exists()
    with patch('desktop.quick_notes_page.QMessageBox.exec', return_value=QMessageBox.StandardButton.Yes):
        page.list_button.click()
    data = lists.read()
    assert data['revision'] == 1 and data['lists'][0]['name'] == 'Einkauf'
    assert [item['done'] for item in data['lists'][0]['items']] == [False, True]
    assert not notes.path.exists() and page.dirty()
    before = lists.path.read_bytes()
    with patch('desktop.quick_notes_page.QMessageBox.exec', return_value=QMessageBox.StandardButton.Yes):
        page.list_button.click()
    assert lists.path.read_bytes() == before and 'bereits' in page.status.text()
    page.title.setText('Andere')
    with patch('desktop.quick_notes_page.QMessageBox.exec', return_value=QMessageBox.StandardButton.Yes), \
         patch('desktop.core.local_state.os.replace', side_effect=PermissionError):
        page.list_button.click()
    assert lists.path.read_bytes() == before and page.dirty()
    page.close()
    app.processEvents()
