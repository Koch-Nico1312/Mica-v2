"""Exercise real local model calls through an isolated MICA API runtime.

Run with a local OpenAI-compatible model server already listening. Never uses
the live Brain, configured credentials, cloud providers or native actions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import tracemalloc
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def verify(url: str, profile: str) -> dict:
    from fastapi.testclient import TestClient
    from backend.services.api.app import create_app
    from backend.services.common.cognition import CognitiveController, CognitiveState

    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.username or parsed.password:
        raise ValueError('Use a loopback HTTP model server.')
    token = secrets.token_hex(24)
    os.environ.update(MICA_API_TOKEN=token, MICA_LLM_PROVIDER='ollama',
                      LLAMA_URL=url.rstrip('/'), MICA_LLM_FALLBACK_URL='',
                      MICA_LAYA_ENABLED='0', MICA_HINDSIGHT_ENABLED='0',
                      MICA_DREAM_RSI_ENABLED='0', MICA_CLOUD_ALLOW_PRIVATE_CONTEXT='0')
    messages = [
        'Mein Testprojekt heißt Sternkarte. Das Ziel ist eine lokale Wetteranzeige.',
        'Wie heißt mein Testprojekt und welches Ziel hat es?',
        'Nein, das Ziel ist eine lokale Anzeige für Pflanzenpflege. Bitte korrigiere deine Antwort.',
        'Wie heißt mein Testprojekt? Nenne nur seinen Namen.',
    ]
    report = {'profile': profile, 'turns': [], 'subjective_experience_tested': False,
              'physical_gpu_compatibility_proven': False}
    with tempfile.TemporaryDirectory(prefix='mica-cognition-') as directory:
        app = create_app(data_dir=directory)
        headers = {'X-Mica-API-Token': token}
        session = 'a' * 32
        with TestClient(app, headers=headers) as client:
            path = f'/v1/dialog/{session}/cognition'
            configured = client.patch(path, json={'enabled': True, 'profile': profile})
            configured.raise_for_status()
            for index, message in enumerate(messages):
                started = time.perf_counter()
                response = client.post('/v1/turns', json={'message': message, 'session_id': session,
                                                        'remember': index == 0, 'response_style': 'brief'})
                response.raise_for_status()
                result = response.json()
                assert result['mode'] == 'local-only'
                assert result['state'] == 'completed'
                assert result['cognition']['turns'] == index + 1
                report['turns'].append({'elapsed_seconds': round(time.perf_counter() - started, 3),
                                        'reply': result['reply'], 'cognition': result['cognition']})
            assert 'sternkarte' in report['turns'][-1]['reply'].casefold(), 'Model did not retain project name.'
            assert report['turns'][2]['cognition']['caution'] >= .4
            client.delete(f'/v1/dialog/{session}').raise_for_status()
            assert client.get(path).json()['turns'] == 0
            report['dialog_reset_verified'] = True
        restarted = create_app(data_dir=directory)
        assert restarted.state.runtime.brain.search('Sternkarte')
        assert len(restarted.state.runtime.brain.documents()) == 1
        with TestClient(restarted, headers=headers) as client:
            response = client.post('/v1/turns', json={'message': 'Wie heißt mein Testprojekt?',
                                                    'session_id': session, 'remember': False,
                                                    'response_style': 'brief'})
            response.raise_for_status()
            result = response.json()
            assert result['retrieval'], 'Restart did not retrieve persistent memory.'
            assert 'sternkarte' in result['reply'].casefold(), 'Model did not use persistent memory.'
            report['restart_reply'] = result['reply']
            report['persistent_memory_verified'] = True
    controller, state = CognitiveController(), CognitiveState(profile=profile)
    evidence = [{'title': 'Testprojekt Sternkarte', 'snippet': 'Lokale Pflanzenpflege ' * 60}] * 5
    tracemalloc.start()
    started = time.perf_counter()
    for _ in range(1000):
        controller.prepare(state, 'Sternkarte Pflanzenpflege', evidence, history=[{}])
        controller.observe(state, reply='Testantwort')
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report['controller_measurement'] = {'iterations': 1000, 'average_ms': round(elapsed, 3),
                                        'python_peak_allocated_bytes': peak,
                                        'additional_model_calls': 0, 'device': 'cpu'}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = [verify(args.model_url, profile) for profile in ('low_vram', 'balanced')]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'schema_version': 1, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'profiles': [item['profile'] for item in results],
                      'output': str(args.output)}, ensure_ascii=False))
