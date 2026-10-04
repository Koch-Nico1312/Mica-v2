"""Bounded, local service probes with concrete recovery instructions."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx


SERVICES = (
    ('llm', 'Sprachmodell', 'LLAMA_URL', 'http://llama-server:8080', {'llama-server', 'llama-fallback'}),
    ('stt', 'Spracherkennung', 'STT_URL', 'http://stt:8091', {'stt'}),
    ('tts', 'Sprachausgabe', 'TTS_URL', 'http://tts:8092', {'tts'}),
    ('broker', 'Aktionsdienst', 'TOOL_BROKER_URL', 'http://tool-broker:8093', {'tool-broker'}),
)


def _probe(spec: tuple) -> dict:
    key, label, variable, default, hosts = spec
    url = os.getenv(variable, default).rstrip('/')
    parsed = urlparse(url)
    item = {'id': key, 'label': label, 'status': 'blocked', 'detail': '', 'remedy': ''}
    if (parsed.scheme != 'http' or parsed.hostname not in hosts | {'localhost', '127.0.0.1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        return {**item, 'detail': 'Dienstadresse ist nicht als lokaler Dienst zugelassen.',
                'remedy': f'{variable} in der Backend-Konfiguration auf den lokalen Compose-Dienst setzen.'}
    try:
        with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client:
            response = client.get(url + '/health')
            response.raise_for_status()
            payload = response.json()
        status = payload.get('status') if isinstance(payload, dict) else None
        ready = status in {'ok', 'ready', 'healthy'}
        item.update(status='ok' if ready else 'blocked', detail=str(status or 'Ungültige Antwort'))
        if not ready:
            item['remedy'] = ('Das konfigurierte Modell und dessen Volume prüfen.' if status == 'model-missing'
                              else 'Konfiguration und Dienstprotokoll prüfen; anschließend erneut testen.')
    except (httpx.HTTPError, ValueError):
        item.update(status='unreachable', detail='Dienst antwortet nicht auf die Zustandsprüfung.',
                    remedy=f'Den Compose-Dienst {key if key != "llm" else "llama-server"} und dessen Protokoll prüfen.')
    return item


def service_diagnostics() -> list[dict]:
    with ThreadPoolExecutor(max_workers=4) as executor:
        return list(executor.map(_probe, SERVICES))
