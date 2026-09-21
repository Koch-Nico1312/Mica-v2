"""Hermetische Testumgebung.

Kein Test darf in die echten Laufzeit-Konfigurationsdateien schreiben:
Jeder Test erhält automatisch isolierte Pfade in ein temporäres Verzeichnis.
Einzelne Tests können dieselben Attribute zusätzlich enger patchen.
"""
import pytest
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = PROJECT_ROOT / "desktop"
BACKEND_ROOT = PROJECT_ROOT / "backend"
for _path in (str(PROJECT_ROOT), str(DESKTOP_ROOT), str(BACKEND_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture(autouse=True)
def _isolated_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setattr("core.automation.AUTOMATION_CONFIG_PATH", tmp_path / "automation.json")
    monkeypatch.setattr("core.smart_home.SMART_HOME_CONFIG_PATH", tmp_path / "smart_home.json")
    monkeypatch.setattr("core.organization.ORGANIZATION_DATA_PATH", tmp_path / "organization.json")
    monkeypatch.setattr("core.learning.LEARNING_DATA_PATH", tmp_path / "learning.json")
    monkeypatch.setattr("core.mica_3d.MICA_3D_CONFIG_PATH", tmp_path / "mica_3d.json")
    monkeypatch.setattr("core.mica_3d.BASE_DIR", tmp_path)
    monkeypatch.setattr("core.intercom_mode.INTERCOM_CONFIG_PATH", tmp_path / "intercom_config.json")
    monkeypatch.setattr("core.autonomous_mode.AUTONOMOUS_MODE_CONFIG_PATH", tmp_path / "autonomous_mode.json")
    monkeypatch.setattr("core.autonomous_server_agent.SERVER_AGENT_CONFIG_PATH", tmp_path / "server_agent.json")
    monkeypatch.setattr("core.personal_dashboard.DASHBOARD_CONFIG_PATH", tmp_path / "dashboard.json")
    yield
