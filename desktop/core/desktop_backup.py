"""Portable desktop settings/state plus a verified backend archive."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
import zipfile
from pathlib import Path
from dataclasses import asdict

from desktop.core.settings_store import FEATURES, SettingsStore, _read_env, _update_env


FILES = ('desktop/memory/long_term.json', 'desktop/memory/organization.json',
         'desktop/config/automation.json', 'desktop/config/provider_profiles.json',
         '.mica-data/preferences.json')
COSMETIC_KEYS = {'assistant_name', 'user_name', 'ui_color', 'voice_name', 'reduced_motion',
                'color_mode', 'face_style', 'camera_index', 'mic_device', 'output_device', 'tts_engine'}
ENV_SETTINGS = {'MICA_LLM_PROVIDER', 'LLAMA_MODEL', 'MICA_LLM_MODEL', 'MICA_OPENAI_MODEL',
                'MICA_GEMINI_MODEL', 'MICA_TTS_ENGINE', 'MICA_TTS_VOICE', 'MICA_CONVERSATION_MODE',
                'MICA_CORE_URL', 'MICA_CORE_CA_FILE'}
MAX_SIZE = 64 * 1024 * 1024


def snapshot(root: Path) -> dict:
    files = {}
    for name in FILES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            content = json.loads(path.read_text(encoding='utf-8'))
            if name == 'desktop/config/provider_profiles.json':
                content = {'schema_version': 1, 'profiles': [asdict(SettingsStore._validated_profile(item)) for item in content['profiles']],
                           'active_profile_id': str(content.get('active_profile_id', ''))}
            files[name] = content
    config = root / 'desktop/config/api_keys.json'
    cosmetic = {}
    if config.is_file() and not config.is_symlink():
        values = json.loads(config.read_text(encoding='utf-8'))
        cosmetic = {key: value for key, value in values.items() if key in COSMETIC_KEYS}
    features = {}
    for scope, path in [('root', root / '.env'), ('backend', root / 'backend/.env')]:
        env = _read_env(path)
        allowed = {feature.key for feature in FEATURES if scope in feature.scopes}
        features[scope] = {key: value for key, value in env.items() if key in allowed and value in {'0', '1'}
                          or key in ENV_SETTINGS and '\n' not in value and '\r' not in value and len(value) <= 160}
    return {'schema': 1, 'files': files, 'ui': cosmetic, 'features': features}


def save_bundle(path: Path, root: Path, backend: bytes) -> dict:
    desktop = json.dumps(snapshot(root), ensure_ascii=False, sort_keys=True).encode('utf-8')
    manifest = {'schema': 1, 'sha256': {name: hashlib.sha256(content).hexdigest()
                                      for name, content in [('desktop.json', desktop), ('backend.tar.gz', backend)]}}
    validate_desktop(json.loads(desktop))
    if len(desktop) + len(backend) + len(json.dumps(manifest)) > MAX_SIZE:
        raise ValueError('Backup ist zu groß für das Desktop-Format.')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.partial')
    try:
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            archive.writestr('desktop.json', desktop)
            archive.writestr('backend.tar.gz', backend)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return {'path': str(path), 'desktop_files': len(json.loads(desktop)['files']), 'backend_bytes': len(backend)}


def read_bundle(path: Path) -> tuple[dict, bytes]:
    if path.stat().st_size > MAX_SIZE:
        raise ValueError('Backup ist zu groß.')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if set(names) != {'manifest.json', 'desktop.json', 'backend.tar.gz'} or len(names) != 3:
            raise ValueError('Backup enthält unerwartete oder doppelte Dateien.')
        if sum(info.file_size for info in archive.infolist()) > MAX_SIZE:
            raise ValueError('Entpacktes Backup ist zu groß.')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('schema') != 1:
            raise ValueError('Unbekanntes Backup-Format.')
        desktop_raw, backend = archive.read('desktop.json'), archive.read('backend.tar.gz')
        for name, content in [('desktop.json', desktop_raw), ('backend.tar.gz', backend)]:
            if hashlib.sha256(content).hexdigest() != manifest.get('sha256', {}).get(name):
                raise ValueError('Backup-Prüfsumme stimmt nicht überein.')
    desktop = json.loads(desktop_raw)
    validate_desktop(desktop)
    return desktop, backend


def validate_desktop(value: dict):
    if not isinstance(value, dict) or value.get('schema') != 1 or set(value) != {'schema', 'files', 'ui', 'features'}:
        raise ValueError('Ungültige Desktop-Sicherung.')
    if not isinstance(value['files'], dict) or set(value['files']) - set(FILES):
        raise ValueError('Nicht zugelassene Desktop-Datei.')
    for name, content in value['files'].items():
        if not isinstance(content, (dict, list)):
            raise ValueError('Ungültiger Desktop-Dateiinhalt.')
        if name == 'desktop/config/provider_profiles.json':
            if not isinstance(content, dict) or content.get('schema_version') != 1 or set(content) - {'profiles', 'active_profile_id', 'schema_version'}:
                raise ValueError('Ungültiges Anbieterprofil-Dokument.')
            for profile in content.get('profiles', []):
                if set(profile) - {'id', 'name', 'provider', 'model', 'credential_name'}:
                    raise ValueError('Nicht zugelassene Anbieterprofil-Felder.')
                SettingsStore._validated_profile(profile)
    if not isinstance(value['ui'], dict) or set(value['ui']) - COSMETIC_KEYS:
        raise ValueError('Nicht zugelassene Oberflächeneinstellung.')
    for name, item in value['ui'].items():
        if name == 'reduced_motion':
            valid = isinstance(item, bool)
        elif name in {'camera_index', 'mic_device', 'output_device'}:
            valid = item is None or isinstance(item, (str, int)) and not isinstance(item, bool)
        else:
            valid = isinstance(item, str) and len(item) <= 160
        if not valid:
            raise ValueError('Ungültiger Wert einer Oberflächeneinstellung.')
    prefs = value['files'].get('.mica-data/preferences.json')
    if prefs is not None and (not isinstance(prefs, dict) or set(prefs) != {'remember_conversations'}
                              or not isinstance(prefs['remember_conversations'], bool)):
        raise ValueError('Ungültige Gesprächsspeicher-Einstellung.')
    if not isinstance(value['features'], dict) or set(value['features']) - {'root', 'backend'}:
        raise ValueError('Ungültige Funktionsschalter.')
    for scope, values in value['features'].items():
        allowed = {feature.key for feature in FEATURES if scope in feature.scopes}
        if (not isinstance(values, dict) or set(values) - (allowed | ENV_SETTINGS)
                or any(not isinstance(v, str) or '\n' in v or '\r' in v or len(v) > 160
                       or (k in allowed and v not in {'0', '1'}) for k, v in values.items())):
            raise ValueError('Ungültige Funktionsschalter.')
        if 'MICA_CORE_URL' in values:
            from desktop.core.local_core_client import LocalCoreClient
            client = LocalCoreClient(values['MICA_CORE_URL'])
            client.session.close()


def restore_desktop(root: Path, value: dict) -> dict:
    validate_desktop(value)
    recovery_dir = root / '.mica-data/recovery'
    recovery_dir.mkdir(parents=True, exist_ok=True)
    identifier = uuid.uuid4().hex
    recovery = recovery_dir / f'desktop-{identifier}.json'
    recovery.write_text(json.dumps(snapshot(root), ensure_ascii=False, indent=2), encoding='utf-8')
    targets = [root / name for name in value['files']]
    targets.extend([root / 'desktop/config/api_keys.json', root / '.env', root / 'backend/.env'])
    for target in targets:
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != root.parent):
            raise ValueError('Wiederherstellungsziel darf kein symbolischer Link sein.')
    previous = {target: target.read_bytes() if target.is_file() else None for target in targets}
    try:
        for name, content in value['files'].items():
            _write_json(root / name, content)
        config = root / 'desktop/config/api_keys.json'
        current = json.loads(config.read_text(encoding='utf-8')) if config.is_file() else {}
        current.update(value['ui'])
        _write_json(config, current)
        for scope, values in value['features'].items():
            _update_env(root / ('backend/.env' if scope == 'backend' else '.env'), values)
    except Exception:
        for target, content in previous.items():
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
        raise
    return {'recovery': str(recovery), 'restart_required': True}


def _write_json(target: Path, value):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.restore.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, target)
