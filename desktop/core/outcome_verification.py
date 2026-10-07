"""Evidence for an explicit file or selected window; never infer application success."""
from datetime import datetime, UTC
import hashlib
from pathlib import Path


def file_snapshot(path):
    path = Path(path).expanduser().resolve()
    try:
        if not path.is_file():
            return {'path': str(path), 'exists': False, 'checked_at': datetime.now(UTC).isoformat()}
        before = path.stat()
        if before.st_size > 16 * 1024 * 1024:
            raise ValueError('Dateiprüfung unterstützt höchstens 16 MB.')
        body = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Datei wurde während der Prüfung verändert. Bitte erneut prüfen.')
        return {'path': str(path), 'exists': True, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'modified_ns': after.st_mtime_ns, 'checked_at': datetime.now(UTC).isoformat()}
    except OSError as error:
        raise ValueError('Datei konnte nicht zuverlässig gelesen werden.') from error


def verify_file(path, *, baseline=None, expected_text='', require_changed=False):
    try:
        snapshot = file_snapshot(path)
        if not snapshot['exists']:
            return {'status': 'not_confirmed', 'detail': 'Die ausgewählte Datei existiert nicht.', 'evidence': snapshot}
        if require_changed:
            if not baseline or baseline.get('path') != snapshot['path']:
                return {'status': 'uncertain', 'detail': 'Für diese Datei fehlt eine Ausgangsfassung.', 'evidence': snapshot}
            if baseline.get('exists') and baseline.get('sha256') == snapshot['sha256']:
                return {'status': 'not_confirmed', 'detail': 'Der gespeicherte Dateiinhalt ist gegenüber der Ausgangsfassung unverändert.', 'evidence': snapshot}
        if expected_text:
            body = Path(snapshot['path']).read_bytes()
            if hashlib.sha256(body).hexdigest() != snapshot['sha256']:
                raise ValueError('Datei änderte sich während der Inhaltsprüfung.')
            try:
                text = body.decode('utf-8-sig')
            except UnicodeDecodeError:
                return {'status': 'uncertain', 'detail': 'Inhalt ist kein UTF-8-Text. Die erwartete Textstelle wurde nicht geprüft.', 'evidence': snapshot}
            if expected_text not in text:
                return {'status': 'not_confirmed', 'detail': 'Die erwartete Textstelle ist im gespeicherten Inhalt nicht enthalten.', 'evidence': snapshot}
        detail = 'Datei ist vorhanden und lesbar.'
        if require_changed:
            detail += ' Der gespeicherte Inhalt wurde verändert.'
        if expected_text:
            detail += ' Die erwartete Textstelle wurde gefunden.'
        return {'status': 'confirmed', 'detail': detail + ' Geprüft wurde nur dieser Dateiinhalt.', 'evidence': snapshot}
    except ValueError as error:
        return {'status': 'uncertain', 'detail': str(error), 'evidence': {}}


def window_snapshot(target, *, reader=None):
    if reader is None:
        from desktop.core.window_controls import read_window_controls
        reader = read_window_controls
    data = reader(target)
    return {'window': target.get('title', ''), 'hwnd': target['hwnd'], 'pid': target['pid'],
        'checked_at': datetime.now(UTC).isoformat(), 'status': data.get('status'),
        'text': data.get('text', ''), 'truncated': data.get('truncated', False)}


def verify_window(target, expected_text, *, reader=None, baseline=None, require_changed=False):
    if not expected_text.strip():
        raise ValueError('Bitte den erwarteten sichtbaren Text samt Zustand angeben.')
    evidence = window_snapshot(target, reader=reader)
    data = evidence
    if data.get('status') != 'read':
        return {'status': 'uncertain', 'detail': 'Das ausgewählte Fenster stellt keinen lesbaren Inhalt bereit.', 'evidence': evidence}
    if expected_text.casefold() not in data.get('text', '').casefold():
        return {'status': 'uncertain', 'detail': 'Erwarteter Text wurde nicht gefunden. Verdeckte Inhalte oder fehlende Bedienelemente erlauben keine Aussage über den Erfolg.', 'evidence': evidence}
    if require_changed:
        if not baseline or baseline.get('status') != 'read' or any(baseline.get(key) != target.get(key) for key in ('hwnd', 'pid')):
            return {'status': 'uncertain', 'detail': 'Für dieses Fenster fehlt eine lesbare Ausgangsfassung.', 'evidence': evidence}
        if expected_text.casefold() in baseline.get('text', '').casefold():
            return {'status': 'not_confirmed', 'detail': 'Der erwartete Text/Zustand war bereits in der Ausgangsfassung vorhanden. Eine neue Änderung ist damit nicht bestätigt.', 'evidence': evidence}
        if baseline.get('truncated'):
            return {'status': 'uncertain', 'detail': 'Die Ausgangsfassung war gekürzt. Eine neue Textstelle lässt sich nicht sicher nachweisen.', 'evidence': evidence}
        return {'status': 'confirmed', 'detail': 'Der erwartete Text/Zustand ist jetzt lesbar und war in der vollständigen Ausgangsfassung noch nicht vorhanden. Dauerhafte Speicherung ist damit nicht bewiesen.', 'evidence': evidence}
    return {'status': 'confirmed', 'detail': 'Erwarteter Text ist im ausgewählten Fenster lesbar. Eine dauerhafte Speicherung dieser Einstellung ist damit nicht bewiesen.', 'evidence': evidence}
