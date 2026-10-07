"""Live local model and native routes, without creating or modifying any tasks."""
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
        assert health['checks']['audit_chain'] and health['checks']['local_llm_url'], health
        result = client.decompose_task('Für die Mathematikprüfung lernen', 'Unterlagen lesen, typische Aufgaben rechnen und Fehler kontrollieren. Insgesamt etwa zwei Stunden.')
        assert result['preview'] and not result['stored']
        assert 2 <= len(result['steps']) <= 12
        assert all(5 <= item['minutes'] <= 240 and item['title'] for item in result['steps'])
        for message, kind in [('Plane meinen Tag', 'task_planning'), ('Aufgaben abgleichen', 'task_planning'),
                ('Zerlege Für die Prüfung lernen in Schritte', 'task_planning'), ('Ergebnis prüfen', 'outcome_check')]:
            reply = client.turn(message)
            assert reply['state'] == 'native_command' and reply['command']['kind'] == kind
        print(json.dumps({'https_verified': True, 'phase0_status': health['status'], 'real_model_steps': len(result['steps']),
            'native_routes': 4, 'tasks_changed': False}, ensure_ascii=False))
    finally:
        client.clear_dialog()
        client.session.close()


if __name__ == '__main__':
    main()
