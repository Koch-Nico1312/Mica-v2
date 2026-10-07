"""Exercise the configured local Core without saving conversations or tasks."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from desktop.core.settings_store import _read_env
    from desktop.core.local_core_client import LocalCoreClient
    settings = _read_env(ROOT / 'backend/.env')
    host, port = settings.get('MICA_PUBLIC_HOST', 'localhost'), settings.get('MICA_HTTPS_PORT', '443')
    url = f'https://{host}' + (':' + port if port != '443' else '')
    ca = Path(settings['MICA_DATA_DIR']) / 'caddy/caddy/pki/authorities/local/root.crt'
    client = LocalCoreClient(base_url=url, ca_file=ca)
    document = {'id': 'b' * 32, 'title': 'MICA-Prüfnotiz.md', 'source': 'text',
        'body': 'Die ausschließlich für diese Prüfung erfundene Anwendung Projektprobe verwendet Port 7251.\nVorher verwendete Projektprobe Port 7250.'}
    try:
        client.resume_workspace(None, 'Den Port von Projektprobe prüfen', [document])
        response = client.turn('Welchen Port verwendet Projektprobe laut der ausgewählten Prüfnotiz?', remember=False)
        assert response.get('mode') == 'local-only', 'Diese Prüfung erwartet ein lokales Modell.'
        assert response.get('document_sources'), 'Die laufende API enthält die Quellenfunktion nicht.'
        assert '7251' in response['reply'], 'Die Dokumentantwort hat den bekannten Prüfport nicht wiedergegeben.'
        for source in response['document_sources']:
            assert source['quote'] == document['body'][source['start']:source['end']]
            assert source['title'] == document['title']
        assert 'MICA-Prüfnotiz.md' in response['reply']
        command_checks = {}
        for message, kind in [('Wechsle zu MICA', 'project_switch'),
                ('Was weißt du über Projekt MICA?', 'memory_project'),
                ('Was hat sich seit gestern geändert?', 'document_changes'),
                ('Wo ändere ich diese Einstellung?', 'window_help')]:
            result = client.turn(message)
            assert result.get('command', {}).get('kind') == kind
            command_checks[kind] = True
        explanation = client.transform_text('Änderung in Projektprobe:\n-Port: 7250\n+Port: 7251\nErkläre die Änderung.', 'explain')
        assert '7251' in explanation['reply'] and explanation.get('stored') is False
        print(json.dumps({'https_core': True, 'local_model_document_answer': True,
            'verified_passages': len(response['document_sources']),
            'model_citations': len(response.get('citations', [])),
            'diff_explanation': True, 'commands': command_checks,
            'new_conversations_or_tasks_saved': False}))
    finally:
        client.clear_dialog()
        client.session.close()


if __name__ == '__main__':
    main()
