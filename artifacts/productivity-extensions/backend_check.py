"""Exercise the built API image with temporary state and a controlled model stub."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock
from fastapi.testclient import TestClient
from backend.services.api.app import create_app

os.environ.update(MICA_API_TOKEN='acceptance-test-token-xxxxxxxxxxxxx', MICA_APPROVAL_SECRET='acceptance-secret',
                  MICA_PHASE3_ENABLED='1', MICA_LAYA_ENABLED='0', MICA_HINDSIGHT_ENABLED='0')
session = 'a' * 32
with tempfile.TemporaryDirectory() as temporary:
    app = create_app(data_dir=Path(temporary))
    runtime = app.state.runtime
    runtime._local_completion = Mock(return_value='Kontrollierte Modellvorschau')
    with TestClient(app, headers={'X-Mica-API-Token': os.environ['MICA_API_TOKEN']}) as client:
        task = client.post('/v1/task-items', json={'title': 'API-Image prüfen', 'description': 'Fortsetzen nach Neustart'}).json()
        context = {'session_id': session, 'message': 'Zeige Aufgabe API-Image prüfen', 'remember': False}
        assert client.post('/v1/turns', json=context).status_code == 200
        assert client.get(f'/v1/dialog/{session}/workspace').json()['task_id'] == task['id']
        assert client.post('/v1/dialog/workspace/resume', json={'session_id': session, 'task_id': task['id'], 'next_step': 'Container prüfen'}).status_code == 200
        for operation in ('explain', 'summarize', 'translate', 'rewrite'):
            response = client.post('/v1/text/transform', json={'text': 'Kontrollierter Beispieltext', 'operation': operation})
            assert response.status_code == 200 and response.json()['preview'] is True
        assert not runtime.brain.documents()
        assert 'API-Image prüfen' in client.get('/v1/day-overview').json()['reply']
        command = client.post('/v1/turns', json={**context, 'message': 'Antworte bei technischen Fragen kürzer', 'remember': True, 'native_commands': True}).json()
        assert command['command']['kind'] == 'preference_offer' and not runtime.evolution.preferences()
        client.post('/v1/auth/approval-session', json={'secret': os.environ['MICA_APPROVAL_SECRET']})
        draft = {key: command['command'][key] for key in ('key', 'value', 'scope')}
        draft['source'] = 'Container-Abnahme'
        response = client.post('/v1/evolution/preferences', json=draft, headers={'X-Mica-Approval-Intent': 'confirm'})
        assert response.status_code == 200
    result = {'workspace_task_and_next_step': True, 'four_text_preview_operations': True, 'overview': True,
              'authenticated_preference_confirmation': True, 'no_selected_text_transcript': True,
              'temporary_state_only': True, 'real_external_model_used': False}
    print(json.dumps(result))
