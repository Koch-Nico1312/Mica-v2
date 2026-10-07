"""Check real HTTPS/local-model drafts without storing user or test tasks."""
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
    document = {'id': 'c' * 32, 'title': 'MICA-Erweiterungsprobe.md', 'source': 'text',
        'body': 'Aufgabe: Berechne die Fläche eines Rechtecks mit Länge 8 cm und Breite 3 cm.\nDie Formel für die Fläche lautet Länge mal Breite.\nDie Abgabe ist am 9. Oktober 2026 um 16:00 Uhr in Wien.'}
    checks = {}
    try:
        for operation in ('tasks', 'cards'):
            result = client.document_drafts([document], operation, 'Erstelle genau einen Vorschlag aus diesem Dokument.')
            assert result['preview'] and not result['stored']
            assert result['items']
            for item in result['items']:
                source = item['source']
                assert source['quote'] == document['body'][source['start']:source['end']]
                if operation == 'cards':
                    assert item['answer'] == source['quote']
            checks[operation] = len(result['items'])
        transformed = client.transform_text('Wir prüfen zuerst die Formel. Danach rechnen wir die Fläche aus.', 'bullets')
        assert transformed['reply'] and not transformed['stored']
        checks['dictation_bullets'] = True
        for message, kind in [('Erstelle einen Schulmodus: Unterlagen öffnen, 45 Minuten Fokus und danach Pause.', 'routine_draft'),
                ('Mach aus diesem Arbeitsblatt meine Aufgaben für diese Woche.', 'document_tasks'),
                ('Lernkarten erstellen', 'document_cards'), ('Lernkarten wiederholen', 'review_cards'), ('Diktiermodus starten', 'dictation')]:
            result = client.turn(message, remember=kind == 'review_cards')
            assert result['command']['kind'] == kind
        checks['new_command_routes'] = True
        print(json.dumps({'https': True, 'real_local_model': checks, 'tasks_or_cards_saved': False}))
    finally:
        client.clear_dialog()
        client.session.close()


if __name__ == '__main__':
    main()
