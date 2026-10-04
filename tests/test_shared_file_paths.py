"""The receipt and executor must address exactly the same files."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from mica_shared import file_paths


@pytest.mark.parametrize('params', [
    {'action': 'create_file', 'name': 'note.txt'},
    {'action': 'write', 'path': 'desktop/notes/file.txt'},
    {'action': 'rename', 'path': 'downloads/old.txt', 'new_name': 'new.txt'},
    {'action': 'copy', 'path': 'documents/source.txt', 'destination': 'desktop'},
    {'action': 'move', 'path': 'documents/source.txt', 'destination': 'pictures/new.txt'},
    {'action': 'organize_desktop'},
    {'action': 'undo_change'},
])
def test_handler_adapter_and_history_share_addressing(tmp_path, monkeypatch, params):
    monkeypatch.setattr(file_paths, 'user_directory', lambda name: tmp_path / name)
    (tmp_path / 'Desktop').mkdir()
    module = importlib.import_module('desktop.actions.file_controller')
    from desktop.core.action_adapters import file_action_paths
    from backend.windows_host_agent.history import file_action_paths as receipt_paths
    assert file_action_paths(params) == receipt_paths(params)
    assert module._resolve_path('"desktop\\notes/file.txt"') == tmp_path / 'Desktop/notes/file.txt'


def test_history_can_be_imported_without_loading_desktop():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([
        sys.executable, '-c',
        "import sys; import backend.windows_host_agent.history; "
        "assert not any(name.startswith(('desktop', 'actions', 'core')) for name in sys.modules)",
    ], cwd=root, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
