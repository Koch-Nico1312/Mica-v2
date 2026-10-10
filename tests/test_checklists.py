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
