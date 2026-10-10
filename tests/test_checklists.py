import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
from desktop.core.checklists import ChecklistStore
from desktop.core.local_state import FileLease
from desktop.checklists_page import ChecklistsPage


def test_lists_restart_and_stale_writer_cannot_lose_checked_items(tmp_path):
    path = tmp_path / 'lists.json'
    first, second = ChecklistStore(path), ChecklistStore(path)
    assert first.read()['lists'] == [] and not path.exists()
    data, identifier = first.change('create', revision=0, text='Einkauf')
    data, _ = first.change('add', revision=data['revision'], list_id=identifier, text='2 Liter Milch')
    stale = second.read()
    item = data['lists'][0]['items'][0]['id']
    checked, _ = first.change('toggle', revision=data['revision'], list_id=identifier, item_id=item, done=True)
    with pytest.raises(ValueError, match='inzwischen'):
        second.change('add', revision=stale['revision'], list_id=identifier, text='Brot')
    reopened = ChecklistStore(path).read()
    assert reopened == checked and reopened['lists'][0]['items'][0]['done']
    reopened, _ = second.change('toggle', revision=reopened['revision'], list_id=identifier, item_id=item, done=False)
    assert not reopened['lists'][0]['items'][0]['done']


def test_duplicate_lists_items_and_failed_storage_preserve_previous_contents(tmp_path):
    path = tmp_path / 'lists.json'
    store = ChecklistStore(path)
    data, identifier = store.change('create', revision=0, text='Einkauf')
    with pytest.raises(ValueError, match='bereits'):
        store.change('create', revision=data['revision'], list_id=identifier, text='einkauf')
    data, _ = store.change('add', revision=data['revision'], list_id=identifier, text='Brot')
    with pytest.raises(ValueError, match='bereits'):
        store.change('add', revision=data['revision'], list_id=identifier, text='brot')
    before = path.read_bytes()
    with patch('desktop.core.checklists.write_json', side_effect=OSError), pytest.raises(OSError):
        store.change('rename', revision=data['revision'], list_id=identifier, text='Packliste')
    assert path.read_bytes() == before


def test_corrupt_state_never_gets_silently_replaced(tmp_path):
    path = tmp_path / 'lists.json'
    path.write_text(json.dumps({'version': 1, 'revision': True, 'lists': []}))
    store = ChecklistStore(path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        store.change('create', revision=0, text='Neue Liste')
    assert path.read_bytes() == before


def test_ui_check_uncheck_cancel_removal_and_privacy(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = ChecklistStore(tmp_path / 'lists.json')
    page = ChecklistsPage(store=store)
    page.name.setText('Urlaub')
    page.create_button.click()
    page.entry.setText('Reisepass')
    page.add_button.click()
    assert page.table.rowCount() == 1
    page.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    assert store.read()['lists'][0]['items'][0]['done']
    page.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not store.read()['lists'][0]['items'][0]['done']
    with patch('desktop.checklists_page.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        page.remove_list()
    assert len(store.read()['lists']) == 1
    page.can_save = lambda: False
    page.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    assert not store.read()['lists'][0]['items'][0]['done']
    assert page.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    page.close()
    app.processEvents()


def test_second_process_cannot_write_during_storage_lease(tmp_path):
    path = tmp_path / 'lists.json'
    store = ChecklistStore(path)
    store.change('create', revision=0, text='Einkauf')
    before = path.read_bytes()
    code = (
        'import sys\n'
        'from pathlib import Path\n'
        'from desktop.core.checklists import ChecklistStore\n'
        'try:\n'
        ' ChecklistStore(Path(sys.argv[1])).change("create", revision=1, text="Urlaub")\n'
        'except ValueError as error:\n'
        ' print(error)\n'
        'else:\n'
        ' raise SystemExit("Unexpected concurrent write")\n'
    )
    with FileLease(str(path) + '.lock'):
        result = subprocess.run([sys.executable, '-c', code, str(path)],
                                cwd=Path(__file__).resolve().parents[1],
                                text=True, encoding='utf-8', capture_output=True, timeout=10,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        assert result.returncode == 0, result.stderr
        assert 'anderen Mica-Instanz' in result.stdout
        assert path.read_bytes() == before
    data, _ = store.change('create', revision=1, text='Urlaub')
    assert len(data['lists']) == 2


def test_atomic_replace_failure_keeps_state_and_removes_temporary_file(tmp_path):
    path = tmp_path / 'lists.json'
    store = ChecklistStore(path)
    data, identifier = store.change('create', revision=0, text='Einkauf')
    before = path.read_bytes()
    existing = set(tmp_path.iterdir())
    with patch('desktop.core.local_state.os.replace', side_effect=PermissionError('locked')):
        with pytest.raises(PermissionError):
            store.change('rename', revision=data['revision'], list_id=identifier, text='Urlaub')
    assert path.read_bytes() == before
    assert set(tmp_path.iterdir()) == existing
    data, _ = store.change('rename', revision=data['revision'], list_id=identifier, text='Urlaub')
    assert data['lists'][0]['name'] == 'Urlaub'


def test_template_duplicate_reset_restart_and_stale_writer(tmp_path):
    store = ChecklistStore(tmp_path / 'lists.json')
    data, original = store.change('from_template', revision=0, text='Wochenende', template='Reise')
    assert len(data['lists'][0]['items']) == 6
    item_id = data['lists'][0]['items'][0]['id']
    data, _ = store.change('toggle', revision=1, list_id=original, item_id=item_id, done=True)
    before_copy = data
    data, copied = store.change('duplicate', revision=2, list_id=original, text='Nächste Reise')
    assert copied != original and data['lists'][0] == before_copy['lists'][0]
    assert [item['text'] for item in data['lists'][1]['items']] == [item['text'] for item in data['lists'][0]['items']]
    assert not any(item['done'] for item in data['lists'][1]['items'])
    original_ids = {item['id'] for item in data['lists'][0]['items']}
    assert original_ids.isdisjoint(item['id'] for item in data['lists'][1]['items'])
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match='inzwischen'):
        store.change('reset', revision=2, list_id=original)
    assert store.path.read_bytes() == before
    data, _ = store.change('reset', revision=3, list_id=original)
    assert not any(item['done'] for item in data['lists'][0]['items'])
    assert {item['id'] for item in data['lists'][0]['items']} == original_ids
    assert ChecklistStore(store.path).read() == data


def test_template_copy_invalid_requests_and_atomic_failure(tmp_path):
    store = ChecklistStore(tmp_path / 'lists.json')
    data, identifier = store.change('from_template', revision=0, text='Einkauf', template='Einkauf')
    before = store.path.read_bytes()
    for operation, arguments in [
        ('from_template', {'text': 'Andere', 'template': 'Unbekannt'}),
        ('from_template', {'text': 'Andere', 'template': []}),
        ('duplicate', {'text': 'EINKAUF', 'list_id': identifier}),
        ('duplicate', {'text': 'Andere', 'list_id': 'missing'}),
        ('from_template', {'text': 'Mehr\nZeilen', 'template': 'Reise'}),
    ]:
        with pytest.raises(ValueError):
            store.change(operation, revision=1, **arguments)
        assert store.path.read_bytes() == before
    with patch('desktop.core.local_state.os.replace', side_effect=PermissionError('locked')):
        with pytest.raises(PermissionError):
            store.change('duplicate', revision=data['revision'], list_id=identifier, text='Andere')
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob('*.tmp'))


def test_ui_template_preview_privacy_copy_and_reset_confirmation(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = ChecklistStore(tmp_path / 'lists.json')
    privacy = {'save': False}
    page = ChecklistsPage(store=store, can_save=lambda: privacy['save'])
    page.template_choice.setCurrentText('Reise')
    assert 'Reisepass' in page.template_preview.text()
    assert not store.path.exists()
    page.template_button.click()
    assert not store.path.exists() and 'Speicherung' in page.status.text()
    privacy['save'] = True
    page.name.setText('Urlaub')
    page.template_button.click()
    assert page.table.rowCount() == 6
    page.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    before = store.read()
    with patch('desktop.checklists_page.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        page.reset()
    assert store.read() == before
    with patch('desktop.checklists_page.QInputDialog.getText', return_value=('Später', False)):
        page.duplicate()
    assert store.read() == before
    with patch('desktop.checklists_page.QInputDialog.getText', return_value=('Später', True)):
        page.duplicate()
    assert len(store.read()['lists']) == 2 and page.choice.currentText() == 'Später'
    assert not any(item['done'] for item in page.selected_list()['items'])
    page.choice.setCurrentIndex(0)
    with patch('desktop.checklists_page.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
        privacy['save'] = False
        page.reset()
        assert store.read()['lists'][0]['items'][0]['done']
        privacy['save'] = True
        page.reset()
    assert not store.read()['lists'][0]['items'][0]['done']
    page.close()
    app.processEvents()
