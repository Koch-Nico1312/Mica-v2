import os
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from desktop.core.checklists import ChecklistStore
from desktop.core.quick_notes import QuickNotesStore
from desktop.core.markdown_export import checklist_markdown, note_markdown, save_markdown
from desktop.checklists_page import ChecklistsPage
from desktop.quick_notes_page import QuickNotesPage


def test_markdown_preserves_checks_and_exports_literal_content():
    record = {'name': 'Einkauf [heute]', 'items': [
        {'text': '<script>Text</script>', 'done': True},
        {'text': '![Bild](https://example.com/track)', 'done': False}]}
    text = checklist_markdown(record, fresh=False)
    assert '- [x] \\<script\\>' in text and '- [ ] \\!\\[Bild\\]' in text
    assert 'ältere Ansicht' in text and 'Einkauf \\[heute\\]' in text
    assert 'keine Einträge' in checklist_markdown({'name': 'Leer', 'items': []}, fresh=True)
    draft = note_markdown('Idee', 'Zeile eins\n# Titel\n![Bild](url)', saved=False)
    assert 'noch nicht in MICA gespeichert' in draft
    assert '\\# Titel' in draft and '\\!\\[Bild\\]' in draft
    assert 'noch nicht' not in note_markdown('Idee', 'Text', saved=True)


def test_atomic_export_failure_preserves_old_file_and_cleans_temporary(tmp_path):
    target = tmp_path / 'Notiz.md'
    target.write_text('Alt', encoding='utf-8')
    with patch('desktop.core.markdown_export.Path.replace', side_effect=PermissionError('locked')):
        with pytest.raises(PermissionError):
            save_markdown(target, 'Neu')
    assert target.read_text(encoding='utf-8') == 'Alt'
    assert not list(tmp_path.glob('.mica-markdown-*.tmp'))
    save_markdown(target, 'Änderung\nNächste Zeile\n')
    assert target.read_bytes() == 'Änderung\nNächste Zeile\n'.encode('utf-8')


def test_notes_export_uses_visible_draft_preserves_storage_and_checks_privacy(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = QuickNotesStore(tmp_path / 'notes.json')
    privacy = {'save': True}
    page = QuickNotesPage(store=store, can_save=lambda: privacy['save'])
    page.title.setText('Idee')
    page.body.setPlainText('Gespeichert')
    page.save()
    original = store.path.read_bytes()
    page.body.setPlainText('Sichtbarer Entwurf')
    target = tmp_path / 'Notiz.md'
    with patch('desktop.quick_notes_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
        page.export_button.click()
    assert 'Sichtbarer Entwurf' in target.read_text(encoding='utf-8')
    assert 'noch nicht' in target.read_text(encoding='utf-8')
    assert store.path.read_bytes() == original and page.dirty()
    before = target.read_bytes()
    privacy['save'] = False
    with patch('desktop.quick_notes_page.QFileDialog.getSaveFileName') as dialog:
        page.export()
    dialog.assert_not_called()
    assert target.read_bytes() == before
    privacy['save'] = True
    def revoke(*args):
        privacy['save'] = False
        return str(target), ''
    with patch('desktop.quick_notes_page.QFileDialog.getSaveFileName', side_effect=revoke):
        page.export()
    assert target.read_bytes() == before
    privacy['save'] = True
    with patch('desktop.quick_notes_page.QFileDialog.getSaveFileName', return_value=('', '')):
        page.export()
    assert target.read_bytes() == before and page.dirty()
    page.close()
    app.processEvents()


def test_checklist_export_records_stale_snapshot_and_leaves_latest_state_alone(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = ChecklistStore(tmp_path / 'lists.json')
    data, identifier = store.change('from_template', revision=0, text='Einkauf', template='Einkauf')
    page = ChecklistsPage(store=store)
    item_id = data['lists'][0]['items'][0]['id']
    store.change('toggle', revision=1, list_id=identifier, item_id=item_id, done=True)
    before = store.path.read_bytes()
    target = tmp_path / 'Liste.md'
    with patch('desktop.checklists_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
        page.export_button.click()
    text = target.read_text(encoding='utf-8')
    assert 'ältere Ansicht' in text and '- [ ] Obst' in text
    assert store.path.read_bytes() == before
    previous = target.read_bytes()
    with patch('desktop.core.markdown_export.Path.replace', side_effect=PermissionError), \
         patch('desktop.checklists_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
        page.export()
    assert 'nicht exportiert' in page.status.text() and target.read_bytes() == previous
    page.can_save = lambda: False
    with patch('desktop.checklists_page.QFileDialog.getSaveFileName') as dialog:
        page.export()
    dialog.assert_not_called()
    page.close()
    app.processEvents()


def test_list_export_contains_only_visible_entries_and_filter_description(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = ChecklistStore(tmp_path / 'lists.json')
    data, identifier = store.change('create', revision=0, text='Einkauf')
    store.change('add_many', revision=1, list_id=identifier, items=[
        {'text': 'Milch', 'done': False}, {'text': 'Milch Alternative', 'done': True},
        {'text': 'Brot', 'done': False}])
    page = ChecklistsPage(store=store)
    page.only_open.setChecked(True)
    page.search.setText('Milch')
    before = store.path.read_bytes()
    target = tmp_path / 'Sichtbar.md'
    with patch('desktop.checklists_page.QFileDialog.getSaveFileName', return_value=(str(target), '')):
        page.export()
    text = target.read_text(encoding='utf-8')
    assert '- [ ] Milch' in text and 'Nur offene Einträge' in text and 'Suche: Milch' in text
    assert 'Alternative' not in text and 'Brot' not in text
    assert store.path.read_bytes() == before
    page.close()
    app.processEvents()


def test_note_copy_is_explicit_works_without_storage_and_preserves_draft(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = QuickNotesStore(tmp_path / 'notes.json')
    clipboard = Mock()
    value = {'text': 'Vorheriger fremder Text'}
    clipboard.setText.side_effect = lambda text: value.update(text=text)
    clipboard.text.side_effect = lambda: value['text']
    with patch('desktop.quick_notes_page.QApplication.clipboard', return_value=clipboard):
        page = QuickNotesPage(store=store, can_save=lambda: False)
        page.title.setText('Idee')
        page.body.setPlainText('Mein Entwurf')
        clipboard.setText.assert_not_called()
        page.copy_button.click()
        assert 'Mein Entwurf' in value['text'] and 'noch nicht' in value['text']
        assert page.dirty() and not store.path.exists() and 'kopiert' in page.status.text()
        previous = value['text']
        page.body.clear()
        page.copy_markdown()
        assert value['text'] == previous and 'Nicht kopiert' in page.status.text()
        page.body.setPlainText('Anderer Entwurf')
        clipboard.setText.side_effect = OSError('locked')
        page.copy_markdown()
        assert value['text'] == previous and 'Nicht kopiert' in page.status.text()
        clipboard.setText.side_effect = None
        page.copy_markdown()
        assert 'Nicht kopiert' in page.status.text() and page.dirty()
        page.close()
    app.processEvents()
