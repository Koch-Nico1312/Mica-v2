"""Check transcription-only dictation with local synthesized test speech."""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from backend.windows_launcher import _docker_executable
    from desktop.core.settings_store import load_desktop_feature_environment
    from desktop.core.local_core_client import LocalCoreClient
    load_desktop_feature_environment(ROOT)
    script = """import base64, httpx
with httpx.Client(trust_env=False, timeout=120) as client:
    health = client.get('http://tts:8092/health').json()
    assert health['engine'] in ('kokoro', 'piper'), 'This test requires local synthesis'
    response = client.post('http://tts:8092/v1/synthesize', json={'text': 'Dies ist ein kurzer Test für das Diktieren.'})
    response.raise_for_status()
    print(base64.b64encode(response.content).decode())
"""
    result = subprocess.run([_docker_executable(), 'exec', 'mica-mica-api-1', 'python', '-c', script],
        capture_output=True, check=True, timeout=150)
    with wave.open(io.BytesIO(base64.b64decode(result.stdout))) as sample:
        assert sample.getsampwidth() == 2
        rate, channels = sample.getframerate(), sample.getnchannels()
        audio = np.frombuffer(sample.readframes(sample.getnframes()), dtype='<i2').astype(np.float32) / 32768
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        audio = np.interp(np.arange(round(len(audio) * 16000 / rate)) * rate / 16000, np.arange(len(audio)), audio)
    assert len(audio) <= 160000
    pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()
    client = LocalCoreClient()
    try:
        response = client.dictate(pcm)
        assert response['storage'] == 'none' and response['text'].strip()
        assert 'test' in response['text'].casefold() or 'diktier' in response['text'].casefold()
        print(json.dumps({'local_synthetic_speech': True, 'https_dictation_transcribed': True,
            'transcription_only': True, 'audio_or_tasks_saved': False, 'physical_microphone': False}))
    finally:
        client.session.close()


if __name__ == '__main__':
    main()
