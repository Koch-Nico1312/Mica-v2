"""Hermetische Testumgebung.

Kein Test darf in die echten Laufzeit-Konfigurationsdateien schreiben:
Jeder Test erhält automatisch isolierte Pfade in ein temporäres Verzeichnis.
Einzelne Tests können dieselben Attribute zusätzlich enger patchen.
"""
import pytest
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _isolated_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_API_TOKEN', 'mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
    monkeypatch.setenv('MICA_ACTION_HISTORY_PATH', str(tmp_path / 'action-history.sqlite3'))
    monkeypatch.setenv('MICA_PREFERENCES_PATH', str(tmp_path / 'preferences.json'))
    monkeypatch.setenv('MICA_HOST_HISTORY_PATH', str(tmp_path / 'host-history.sqlite3'))
    monkeypatch.setattr("desktop.core.automation.AUTOMATION_CONFIG_PATH", tmp_path / "automation.json")
    monkeypatch.setattr("desktop.core.smart_home.SMART_HOME_CONFIG_PATH", tmp_path / "smart_home.json")
    monkeypatch.setattr("desktop.core.organization.ORGANIZATION_DATA_PATH", tmp_path / "organization.json")
    monkeypatch.setattr("desktop.core.learning.LEARNING_DATA_PATH", tmp_path / "learning.json")
    monkeypatch.setattr("desktop.core.mica_3d.MICA_3D_CONFIG_PATH", tmp_path / "mica_3d.json")
    monkeypatch.setattr("desktop.core.mica_3d.BASE_DIR", tmp_path)
    monkeypatch.setattr("desktop.core.intercom_mode.INTERCOM_CONFIG_PATH", tmp_path / "intercom_config.json")
    monkeypatch.setattr("desktop.core.autonomous_mode.AUTONOMOUS_MODE_CONFIG_PATH", tmp_path / "autonomous_mode.json")
    monkeypatch.setattr("desktop.core.personal_dashboard.DASHBOARD_CONFIG_PATH", tmp_path / "dashboard.json")
    yield
