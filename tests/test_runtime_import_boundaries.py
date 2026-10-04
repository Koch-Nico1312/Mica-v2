"""Catch duplicate module identities and omissions from the container layout."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_imports_use_canonical_packages():
    aliases = {'core', 'services', 'actions', 'memory', 'plugins', 'dashboard', 'ui', 'main', 'legacy', 'control_center', 'config'}
    violations = []
    for directory in ('desktop', 'backend'):
        for file in (ROOT / directory).rglob('*.py'):
            tree = ast.parse(file.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                    [node.module] if isinstance(node, ast.ImportFrom) and not node.level and node.module else []
                )
                for name in names:
                    if name.split('.')[0] in aliases:
                        violations.append(f'{file.relative_to(ROOT)}:{node.lineno}: {name}')
    assert not violations, '\n'.join(violations)


def test_shared_contracts_have_one_class_identity():
    from mica_shared import capabilities, addressing
    from backend.services.common import capabilities as compatibility_capabilities
    from backend.services.common import addressing as compatibility_addressing
    from desktop.core import addressing_detector
    assert compatibility_capabilities.CapabilityManifest is capabilities.CapabilityManifest
    assert compatibility_addressing.AddressDecision is addressing.AddressDecision
    assert addressing_detector.AddressDecision is addressing.AddressDecision
    assert addressing_detector.AddressingDetector is addressing.AddressingDetector


def test_optional_desktop_actions_import_without_desktop_path_aliases(tmp_path):
    environment = dict(os.environ, PYTHONPATH=str(ROOT))
    script = (
        "import sys; import desktop.config as configuration; "
        "from desktop.actions import game_updater, flight_finder, youtube_video; "
        "assert all(module.is_windows is configuration.is_windows for module in "
        "(game_updater, flight_finder, youtube_video)); "
        "assert 'config' not in sys.modules"
    )
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_python_container_layout_imports_factory_without_desktop(tmp_path):
    image = tmp_path / 'image'
    shutil.copytree(ROOT / 'backend/services', image / 'backend/services', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT / 'mica_shared', image / 'mica_shared', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT / 'backend/backup_restore.py', image / 'backend/backup_restore.py')
    environment = dict(os.environ, PYTHONPATH=str(image))
    script = (
        'import sys; from backend.services.api.app import create_app; '
        'from backend.services.common.health import fresh; '
        'from backend.backup_restore import create_backup; '
        'from mica_shared.capabilities import CapabilityManifest; '
        'assert not any(name == "desktop" or name.startswith("desktop.") for name in sys.modules); '
        'assert not any(name == "services" or name.startswith("services.") for name in sys.modules)'
    )
    result = subprocess.run([sys.executable, '-c', script], cwd=image, env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
