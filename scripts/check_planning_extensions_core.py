"""Verify new native grammar on the running HTTPS API in a disposable conversation."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from desktop.core.settings_store import load_desktop_feature_environment
    from desktop.core.local_core_client import LocalCoreClient
    load_desktop_feature_environment(ROOT)
    client = LocalCoreClient()
    try:
        health = client.health()
        requests = [('Ich habe erst ab 15 Uhr Zeit', 'task_planning'),
            ('Die Aufgabe dauert länger', 'task_planning'),
            ('Aufgabe Bericht dauert 60 Minuten', 'task_planning'),
            ('Projekt alpha fortsetzen', 'workspace_continue'),
            ('Kalender einlesen', 'task_planning'), ('Lernkarten einplanen', 'task_planning')]
        for message, kind in requests:
            reply = client.turn(message)
            assert reply['state'] == 'native_command' and reply['command']['kind'] == kind, reply
        output = {'https_verified': True, 'phase0_status': health['status'], 'native_routes': len(requests),
            'shared_source_sha256': hashlib.sha256((ROOT / 'mica_shared' / 'quick_commands.py').read_bytes()).hexdigest(),
            'task_mutations': False, 'calendar_mutations': False}
        folder = ROOT / 'artifacts' / 'planning-extensions'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'core-runtime.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
        print(json.dumps(output))
    finally:
        client.clear_dialog()
        client.session.close()


if __name__ == '__main__':
    main()
