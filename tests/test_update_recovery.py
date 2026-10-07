from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QMessageBox

from backend.backup_restore import create_backup
from backend.services.common.brain import MarkdownBrain
from desktop.control_center import ControlCenter
from desktop.core.desktop_backup import read_bundle
from desktop.core.update_recovery import inspect_backup, prepare_checkpoint, source_state, verify_checkpoint
from desktop.core.update_recovery import _publish_checkpoint


def test_checkpoint_publication_retries_only_transient_windows_errors(tmp_path, monkeypatch):
    stage, published = tmp_path / 'stage', tmp_path / 'published'
    stage.mkdir()
    (stage / 'manifest.json').write_text('verified')
    rename = Path.rename
    calls = []
    def busy_once(path, target):
        calls.append(path)
        if len(calls) == 1:
            error = PermissionError('temporarily busy')
            error.winerror = 5
            raise error
        return rename(path, target)
    monkeypatch.setattr(Path, 'rename', busy_once)
    sleep = Mock()
    monkeypatch.setattr('desktop.core.update_recovery.time.sleep', sleep)
    _publish_checkpoint(stage, published)
    assert (published / 'manifest.json').read_text() == 'verified'
    assert len(calls) == 2
    sleep.assert_called_once_with(.05)


def test_checkpoint_publication_never_hides_persistent_or_non_windows_permission_failure(tmp_path, monkeypatch):
    stage, published = tmp_path / 'stage', tmp_path / 'published'
    stage.mkdir()
    sleep = Mock()
    monkeypatch.setattr('desktop.core.update_recovery.time.sleep', sleep)
    ordinary = PermissionError('access denied')
    rename = Mock(side_effect=ordinary)
    monkeypatch.setattr(Path, 'rename', rename)
    with pytest.raises(PermissionError):
        _publish_checkpoint(stage, published)
    assert rename.call_count == 1 and not published.exists()
    busy = PermissionError('access denied')
    busy.winerror = 5
    rename.reset_mock()
    rename.side_effect = busy
    with pytest.raises(PermissionError):
        _publish_checkpoint(stage, published)
    assert rename.call_count == 6 and not published.exists()
    assert stage.exists()


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.email', 'test@example.invalid')
    git(root, 'config', 'user.name', 'Test')
    (root / '.gitignore').write_text('/.mica-data/\n', encoding='utf-8')
    (root / 'program.txt').write_text('version one', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'initial')
    data = root / '.mica-data' / 'backend-test'
    MarkdownBrain(data / 'brain', data / 'index' / 'brain.sqlite3').write('memory', 'Note', 'Known data')
    archive, _ = create_backup(data, tmp_path / 'exports')
    client = Mock()
    client.download_backup.return_value = archive.read_bytes()
    return root, client


def test_checkpoint_preserves_source_and_data_without_updating(installation, tmp_path):
    root, client = installation
    before = source_state(root)
    report = prepare_checkpoint(root, client)
    checkpoint = Path(report['path'])
    assert report['passed']
    assert source_state(root) == before
    assert verify_checkpoint(root)['path'] == str(checkpoint)
    desktop, backend = read_bundle(checkpoint / 'data.zip')
    assert desktop['schema'] == 1
    assert backend == client.download_backup.return_value
    restored = tmp_path / 'source-copy'
    subprocess.run(['git', 'clone', '-q', str(checkpoint / 'source.bundle'), str(restored)], check=True, capture_output=True)
    assert (restored / 'program.txt').read_text(encoding='utf-8') == 'version one'
    assert git(restored, 'rev-parse', 'HEAD') == before['head']


@pytest.mark.parametrize('change', ['tracked', 'untracked'])
def test_dirty_project_is_refused_before_backend_export(installation, change):
    root, client = installation
    path = root / ('program.txt' if change == 'tracked' else 'new.txt')
    path.write_text('local work', encoding='utf-8')
    with pytest.raises(ValueError, match='Lokale Änderungen'):
        prepare_checkpoint(root, client)
    client.download_backup.assert_not_called()
    assert path.read_text(encoding='utf-8') == 'local work'


def test_failed_backup_does_not_publish_checkpoint_or_change_source(installation):
    root, client = installation
    before = source_state(root)
    client.download_backup.side_effect = OSError('offline')
    with pytest.raises(OSError):
        prepare_checkpoint(root, client)
    assert list((root / '.mica-data' / 'update-recovery').iterdir()) == []
    assert source_state(root) == before


def test_project_change_during_export_is_preserved_and_refused(installation):
    root, client = installation
    content = client.download_backup.return_value

    def export():
        (root / 'program.txt').write_text('new local work', encoding='utf-8')
        return content

    client.download_backup.side_effect = export
    with pytest.raises(ValueError, match='während'):
        prepare_checkpoint(root, client)
    assert (root / 'program.txt').read_text(encoding='utf-8') == 'new local work'
    assert list((root / '.mica-data' / 'update-recovery').iterdir()) == []


@pytest.mark.parametrize('problem', ['expired', 'future', 'different_head', 'corrupt_data', 'corrupt_source'])
def test_invalid_checkpoint_cannot_authorize_update(installation, problem):
    root, client = installation
    checkpoint = Path(prepare_checkpoint(root, client)['path'])
    manifest_path = checkpoint / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if problem == 'expired':
        manifest['created_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    elif problem == 'future':
        manifest['created_at'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif problem == 'different_head':
        manifest['head'] = '0' * 40
    else:
        (checkpoint / ('data.zip' if problem == 'corrupt_data' else 'source.bundle')).write_bytes(b'corrupted')
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='Keine gültige'):
        verify_checkpoint(root)


def test_backup_inspection_is_read_only_and_rejects_corruption(installation, tmp_path):
    root, client = installation
    checkpoint = Path(prepare_checkpoint(root, client)['path'])
    before = source_state(root)
    assert inspect_backup(checkpoint / 'data.zip')['markdown_documents'] == 1
    backend = tmp_path / 'backend.tar.gz'
    backend.write_bytes(client.download_backup.return_value)
    assert inspect_backup(backend)['backend_only']
    assert source_state(root) == before
    corrupted = tmp_path / 'broken.zip'
    corrupted.write_bytes(b'invalid archive')
    with pytest.raises(Exception):
        inspect_backup(corrupted)


def test_ui_inspection_never_calls_restore(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = ControlCenter()
    page.timer.stop()
    page._timing_timer.stop()
    client = Mock()
    with patch('desktop.control_center.QFileDialog.getOpenFileName', return_value=(str(tmp_path / 'data.zip'), '')), \
            patch('desktop.core.update_recovery.inspect_backup', return_value={'passed': True}) as inspect, \
            patch.object(page, '_run', side_effect=lambda kind, action: action(client)):
        page.inspect_backup_file()
    inspect.assert_called_once()
    client.restore_backup.assert_not_called()
    page.close()
    page.deleteLater()
    app.processEvents()


def test_invalid_restore_is_rejected_before_remote_changes_and_releases_ui(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = ControlCenter()
    page.timer.stop()
    page._timing_timer.stop()
    events = []
    page.restore_busy.connect(events.append)
    client = Mock()
    path = tmp_path / 'broken.tar.gz'
    path.write_bytes(b'not a backup')

    def perform(kind, action):
        try:
            value = action(client)
        except Exception as error:
            page._received(kind, None, str(error))
        else:
            page._received(kind, value, '')

    with patch('desktop.control_center.QFileDialog.getOpenFileName', return_value=(str(path), '')), \
            patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
            patch.object(page, '_run', side_effect=perform):
        page.restore_backup()
    client.restore_backup.assert_not_called()
    assert events == [True, False]
    assert 'fehlgeschlagen' in page.backup_report.toPlainText()
    page.close()
    page.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('checkpoint_ready', [False, True])
def test_actual_launcher_function_only_fast_forwards_with_verified_checkpoint(installation, tmp_path, checkpoint_ready):
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell:
        pytest.skip('PowerShell unavailable')
    root, client = installation
    branch = git(root, 'symbolic-ref', '--short', 'HEAD')
    remote = tmp_path / 'remote.git'
    donor = tmp_path / 'donor'
    subprocess.run(['git', 'clone', '--bare', '-q', str(root), str(remote)], check=True, capture_output=True)
    subprocess.run(['git', 'clone', '-q', str(remote), str(donor)], check=True, capture_output=True)
    git(donor, 'config', 'user.email', 'test@example.invalid')
    git(donor, 'config', 'user.name', 'Test')
    (donor / 'program.txt').write_text('version two', encoding='utf-8')
    git(donor, 'add', '.')
    git(donor, 'commit', '-qm', 'next version')
    git(donor, 'push', '-q', 'origin', branch)
    git(root, 'remote', 'add', 'origin', str(remote))
    git(root, 'fetch', '-q', 'origin')
    git(root, 'branch', '--set-upstream-to', 'origin/' + branch)
    before = source_state(root)
    if checkpoint_ready:
        prepare_checkpoint(root, client)
    project = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'PYTHONPATH': str(project), 'MICA_SKIP_UPDATE': '0',
                   'TEST_INSTALLER': str(project / 'install_and_start.ps1'),
                   'TEST_PROJECT': str(root), 'TEST_PYTHON': sys.executable}
    script = """
    $ErrorActionPreference = 'Stop'
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($env:TEST_INSTALLER, [ref]$null, [ref]$null)
    $function = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Update-MICA' }, $true)
    Invoke-Expression $function.Extent.Text
    $projectDir = $env:TEST_PROJECT
    $pythonExe = $env:TEST_PYTHON
    $NoUpdate = $false
    Update-MICA
    exit 0
    """
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', script],
                            env=environment, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    if checkpoint_ready:
        assert git(root, 'rev-parse', 'HEAD') == git(donor, 'rev-parse', 'HEAD'), result.stdout + result.stderr
        assert (root / 'program.txt').read_text(encoding='utf-8') == 'version two'
    else:
        assert source_state(root) == before
        assert 'Update skipped' in result.stdout
