"""Small non-secret desktop preferences, also included in UI backups."""
import json
import os
from pathlib import Path


def preferences_path() -> Path:
    return Path(os.getenv('MICA_PREFERENCES_PATH', str(Path(__file__).resolve().parents[2] / '.mica-data/preferences.json')))


def remember_conversations() -> bool:
    try:
        value = json.loads(preferences_path().read_text(encoding='utf-8')).get('remember_conversations', True)
        return value if isinstance(value, bool) else True
    except (OSError, ValueError, AttributeError):
        return True


def set_remember_conversations(value: bool):
    if not isinstance(value, bool):
        raise ValueError('Preference must be boolean')
    target = preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'remember_conversations': value}), encoding='utf-8')
    os.replace(temporary, target)
