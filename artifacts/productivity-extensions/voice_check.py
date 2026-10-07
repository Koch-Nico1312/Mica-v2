"""Real local Redux recognition and TTS; synthetic input, no physical devices."""
import json
from pathlib import Path
import wave
import httpx
from mica_shared.quick_commands import parse_quick_command

directory = Path(__file__).parent
expected = ['day_overview', 'routine', 'preference_offer', 'workspace_resume']
results = []
for index, kind in enumerate(expected):
    with wave.open(str(directory / f'voice-{index}.wav')) as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1 and audio.getsampwidth() == 2
        raw = audio.readframes(audio.getnframes())
    response = httpx.post('http://stt:8091/v1/transcribe', content=raw, headers={'Content-Type': 'application/octet-stream'}, timeout=120)
    response.raise_for_status()
    transcript = response.json()['text']
    command = parse_quick_command(transcript)
    results.append({'transcript': transcript, 'expected_kind': kind, 'recognized_command': command,
                    'matches': bool(command and command['kind'] == kind)})
speech = httpx.post('http://tts:8092/v1/synthesize', json={'text': 'Deine Tagesübersicht ist vorbereitet.'}, timeout=120)
speech.raise_for_status()
result = {'commands': results, 'all_commands_recognized': all(item['matches'] for item in results),
          'real_local_stt': True, 'real_local_tts_audio_bytes': len(speech.content), 'synthetic_input': True,
          'physical_microphone_speaker_verified': False, 'llm_used': False}
(directory / 'voice-runtime.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
assert result['all_commands_recognized'] and result['real_local_tts_audio_bytes'] > 1000
