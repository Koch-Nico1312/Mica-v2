"""Verified data and committed-source checkpoints; never applies a code rollback."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import zipfile

from .desktop_backup import read_bundle, save_bundle


MAX_AGE_SECONDS = 24 * 60 * 60


def _git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                            timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('Git-Prüfung fehlgeschlagen.')
    return result.stdout.strip()


def source_state(root):
    root = Path(root).resolve()
    head = _git(root, 'rev-parse', 'HEAD')
    dirty = bool(_git(root, 'status', '--porcelain', '--untracked-files=all'))
    return {'head': head, 'dirty': dirty}


def inspect_backup(path):
    """Verify in a disposable directory without writing live desktop/backend data."""
    from backend.backup_restore import verify_restore

    path = Path(path)
    if path.name.lower().endswith('.zip'):
        desktop, backend = read_bundle(path)
        with tempfile.TemporaryDirectory(prefix='mica-backup-check-') as directory:
            archive = Path(directory) / 'backend.tar.gz'
            archive.write_bytes(backend)
            report = verify_restore(archive)
        return {'passed': report['passed'], 'desktop_files': len(desktop['files']),
                'markdown_documents': report['markdown_documents'], 'backend_only': False}
    if path.name.lower().endswith('.tar.gz'):
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Backup ist zu groß.')
        report = verify_restore(path)
        return {'passed': report['passed'], 'markdown_documents': report['markdown_documents'], 'backend_only': True}
    raise ValueError('Nicht unterstütztes Backup-Format.')


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _checkpoint_root(root):
    directory = root / '.mica-data' / 'update-recovery'
    if any(path.is_symlink() or path.is_junction() for path in (root, root / '.mica-data', directory)):
        raise ValueError('Update-Sicherungsziel darf kein Link sein.')
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _publish_checkpoint(stage, published):
    """Retry transient Windows sharing/access failures without replacing a target."""
    stage, published = Path(stage), Path(published)
    if (stage.parent.resolve() != published.parent.resolve() or stage.is_symlink()
            or stage.is_junction() or published.exists()):
        raise ValueError('Ungültiges Update-Sicherungsziel.')
    for attempt in range(6):
        try:
            stage.rename(published)
            return
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in {5, 32} or attempt == 5 or published.exists():
                raise
            time.sleep(.05 * 2 ** attempt)


def prepare_checkpoint(root, client):
    root = Path(root).resolve()
    before = source_state(root)
    if before['dirty']:
        raise ValueError('Lokale Änderungen vorhanden. Normales Daten-Backup bleibt verfügbar; kein automatisches Update.')
    destination = _checkpoint_root(root)
    identifier = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='mica-update-', dir=destination) as temporary:
        stage = Path(temporary)
        data = stage / 'data.zip'
        save_bundle(data, root, client.download_backup())
        inspection = inspect_backup(data)
        if not inspection['passed']:
            raise ValueError('Update-Sicherung konnte nicht geprüft werden.')
        source = stage / 'source.bundle'
        _git(root, 'bundle', 'create', str(source), 'HEAD')
        _git(root, 'bundle', 'verify', str(source))
        if source_state(root) != before:
            raise ValueError('Projektstand wurde während der Sicherung verändert; erneut prüfen.')
        manifest = {'schema': 1, 'head': before['head'], 'created_at': datetime.now(timezone.utc).isoformat(),
                    'sha256': {name: _digest(stage / name) for name in ('data.zip', 'source.bundle')}}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        published = destination / identifier
        _publish_checkpoint(stage, published)
    return {'path': str(published), 'head': before['head'], **inspection}


def verify_checkpoint(root):
    from backend.backup_restore import BackupDrillError

    root = Path(root).resolve()
    state = source_state(root)
    if state['dirty']:
        raise ValueError('Lokale Änderungen vorhanden; Update übersprungen.')
    directory = root / '.mica-data' / 'update-recovery'
    if not directory.is_dir():
        raise ValueError('Zuerst unter Betrieb / Backup eine Update-Sicherung erstellen.')
    _checkpoint_root(root)
    now = datetime.now(timezone.utc)
    for checkpoint in sorted(directory.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            if not checkpoint.is_dir() or checkpoint.is_symlink() or checkpoint.is_junction():
                continue
            if uuid.UUID(hex=checkpoint.name).hex != checkpoint.name:
                continue
            paths = [checkpoint / name for name in ('manifest.json', 'data.zip', 'source.bundle')]
            if any(path.is_symlink() or not path.is_file() for path in paths):
                continue
            manifest = json.loads(paths[0].read_text(encoding='utf-8'))
            age = (now - datetime.fromisoformat(manifest['created_at'])).total_seconds()
            if manifest['schema'] != 1 or manifest['head'] != state['head'] or not 0 <= age <= MAX_AGE_SECONDS:
                continue
            if any(_digest(path) != manifest['sha256'][path.name] for path in paths[1:]):
                continue
            _git(root, 'bundle', 'verify', str(paths[2]))
            if f"{state['head']} HEAD" not in _git(root, 'bundle', 'list-heads', str(paths[2])).splitlines():
                continue
            inspection = inspect_backup(paths[1])
            if inspection['passed'] and source_state(root) == state:
                return {'path': str(checkpoint), 'head': state['head'], **inspection}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, BackupDrillError, zipfile.BadZipFile):
            continue
    raise ValueError('Keine gültige Update-Sicherung für diesen Projektstand, höchstens 24 Stunden alt.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_checkpoint(args.root)
    except Exception:
        print('Update nicht freigegeben. Unter Betrieb / Backup eine aktuelle Update-Sicherung erstellen.')
        return 1
    print('Geprüfte Update-Sicherung: ' + report['path'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
