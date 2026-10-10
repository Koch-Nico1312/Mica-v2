import os
from contextlib import contextmanager
import threading
import time
from unittest.mock import patch
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from desktop.core.folder_analysis import analyze_folder
from desktop.folder_analysis_page import FolderAnalysisPage


def test_inventory_is_read_only_bounded_and_sorts_largest_files(tmp_path):
    for index in range(25):
        (tmp_path / f'{index}.dat').write_bytes(b'x' * index)
    nested = tmp_path / 'nested'
    nested.mkdir()
    (nested / 'large.dat').write_bytes(b'x' * 100)
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    result = analyze_folder(tmp_path)
    assert result['complete'] and result['files'] == 26 and result['bytes'] == 400
    assert len(result['largest']) == 20 and result['largest'][0]['bytes'] == 100
    assert {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before
    limited = analyze_folder(tmp_path, max_entries=2)
    assert not limited['complete'] and limited['reason'] == 'entry_limit'
    cancelled = threading.Event()
    cancelled.set()
    result = analyze_folder(tmp_path, cancelled=cancelled)
    assert result['reason'] == 'cancelled' and result['files'] == 0


def test_links_are_skipped_without_reading_outside_selected_folder(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    outside = tmp_path / 'outside.txt'
    outside.write_text('private')
    try:
        (root / 'link').symlink_to(outside)
    except OSError:
        pytest.skip('Symlink creation unavailable on this Windows account')
    result = analyze_folder(root)
    assert result['files'] == 0 and result['skipped_links'] == 1


def test_ui_async_scan_and_cancelled_folder_picker(tmp_path):
    app = QApplication.instance() or QApplication([])
    (tmp_path / 'file.dat').write_bytes(b'abc')
    page = FolderAnalysisPage()
    with patch('desktop.folder_analysis_page.QFileDialog.getExistingDirectory', return_value=''):
        page.choose.click()
    assert not page.busy
    with patch('desktop.folder_analysis_page.QFileDialog.getExistingDirectory', return_value=str(tmp_path)):
        page.choose.click()
    deadline = time.monotonic() + 3
    while page.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert not page.busy
    assert 'Prüfung abgeschlossen' in page.status.text() and 'file.dat' in page.report.toPlainText()
    page.close()


def test_queued_directory_replaced_by_link_is_not_traversed(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    nested = root / 'nested'
    nested.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.txt').write_bytes(b'private')
    probe = tmp_path / 'probe'
    try:
        probe.symlink_to(outside, target_is_directory=True)
        probe.unlink()
    except OSError:
        pytest.skip('Directory symlink creation unavailable')
    real_scandir = os.scandir

    @contextmanager
    def changed_after_listing(directory):
        with real_scandir(directory) as children:
            yield children
        if directory == root:
            nested.rename(tmp_path / 'old_nested')
            nested.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr('desktop.core.folder_analysis.os.scandir', changed_after_listing)
    result = analyze_folder(root)
    assert result['files'] == 0 and result['skipped_links'] == 1
