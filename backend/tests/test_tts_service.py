from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest
import base64
import io
import wave
from unittest.mock import patch

from fastapi.testclient import TestClient

from services import tts_service


class TTSServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(tts_service.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch.dict("os.environ", {}, clear=True)
    def test_health_fails_closed_without_model(self):
        self.assertEqual(self.client.get("/health").json(), {
            "status": "model-missing",
            "engine": "piper",
            "voice": "unconfigured",
        })

    def test_health_requires_matching_config(self):
        model = self.root / "dii_de-DE.onnx"
        model.write_bytes(b"model")
        with patch.dict("os.environ", {"PIPER_MODEL": str(model)}, clear=True):
            self.assertEqual(self.client.get("/health").json()["status"], "model-missing")

            pathlib.Path(str(model) + ".json").write_text("{}", encoding="utf-8")
            self.assertEqual(self.client.get("/health").json(), {
                "status": "ok",
                "engine": "piper",
                "voice": "dii_de-DE",
            })

    def test_synthesis_uses_model_and_matching_config(self):
        model = self.root / "dii_de-DE.onnx"
        config = self.root / "voice.json"
        model.write_bytes(b"model")
        config.write_text("{}", encoding="utf-8")

        def fake_run(command, **kwargs):
            output = command[command.index("--output_file") + 1]
            pathlib.Path(output).write_bytes(b"RIFFtest")
            self.assertEqual(command[command.index("--model") + 1], str(model))
            self.assertEqual(command[command.index("--config") + 1], str(config))
            self.assertEqual(kwargs["input"], "Grüße, 27 und 1.024.")
            return subprocess.CompletedProcess(command, 0, "", "")

        environment = {"PIPER_MODEL": str(model), "PIPER_CONFIG": str(config)}
        with patch.dict("os.environ", environment, clear=True), patch.object(tts_service.subprocess, "run", fake_run):
            response = self.client.post("/v1/synthesize", json={"text": "Grüße, 27 und 1.024."})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/wav")
        self.assertEqual(response.content, b"RIFFtest")

    def test_kokoro_health_and_synthesis_use_all_pinned_files(self):
        model = self.root / "kokoro-v1_0.pth"
        config = self.root / "config.json"
        voice = self.root / "df_kerstin.pt"
        for path in (model, config, voice):
            path.write_bytes(b"local-model-data")
        environment = {
            "MICA_TTS_ENGINE": "kokoro",
            "KOKORO_MODEL": str(model),
            "KOKORO_CONFIG": str(config),
            "KOKORO_VOICE": str(voice),
        }
        with (
            patch.dict("os.environ", environment, clear=True),
            patch.object(tts_service, "_synthesize_kokoro", return_value=b"RIFF-kokoro") as synthesize,
        ):
            health = self.client.get("/health")
            response = self.client.post("/v1/synthesize", json={"text": "Nat�rlich und klar."})

        self.assertEqual(health.json(), {
            "status": "ok", "engine": "kokoro", "voice": "df_kerstin",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"RIFF-kokoro")
        self.assertEqual(synthesize.call_args.args[0], "Nat�rlich und klar.")

    def test_invalid_engine_falls_back_to_piper(self):
        with patch.dict("os.environ", {"MICA_TTS_ENGINE": "unknown"}, clear=True):
            self.assertEqual(self.client.get("/health").json()["engine"], "piper")

    def test_auto_engine_pairs_llm_and_voice_provider(self):
        cases = {
            "gemini": "gemini",
            "google_gemini": "gemini",
            "openai_api": "openai",
            "openai_cloud": "openai",
            "ollama": "kokoro",
        }
        for provider, expected in cases.items():
            with self.subTest(provider=provider), patch.dict("os.environ", {
                "MICA_TTS_ENGINE": "auto", "MICA_LLM_PROVIDER": provider,
            }, clear=True):
                self.assertEqual(tts_service._engine(), expected)

    def test_gemini_tts_uses_same_key_and_returns_wrapped_pcm(self):
        pcm = b"\x01\x00" * 200

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"candidates": [{"content": {"parts": [{"inlineData": {
                    "data": base64.b64encode(pcm).decode("ascii"),
                }}]}}]}

        environment = {
            "MICA_TTS_ENGINE": "auto", "MICA_LLM_PROVIDER": "gemini",
            "GOOGLE_API_KEY": "test-google-key", "MICA_GEMINI_TTS_VOICE": "Sulafat",
        }
        with patch.dict("os.environ", environment, clear=True), patch.object(
            tts_service.httpx, "post", return_value=Response(),
        ) as post:
            response = self.client.post("/v1/synthesize", json={"text": "Gr��e, 27."})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"RIFF"))
        with wave.open(io.BytesIO(response.content), "rb") as wav:
            self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getsampwidth()), (1, 24000, 2))
            self.assertEqual(wav.readframes(wav.getnframes()), pcm)
        request = post.call_args
        self.assertEqual(request.kwargs["headers"]["x-goog-api-key"], "test-google-key")
        self.assertEqual(
            request.kwargs["json"]["generationConfig"]["speechConfig"]
            ["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"],
            "Sulafat",
        )

    def test_openai_tts_uses_official_speech_endpoint_and_wav(self):
        wav_data = b"RIFF" + b"\x00" * 44

        class Response:
            status_code = 200
            content = wav_data

            def raise_for_status(self):
                return None

        environment = {
            "MICA_TTS_ENGINE": "auto", "MICA_LLM_PROVIDER": "openai_api",
            "OPENAI_API_KEY": "test-openai-key", "MICA_OPENAI_TTS_VOICE": "coral",
        }
        with patch.dict("os.environ", environment, clear=True), patch.object(
            tts_service.httpx, "post", return_value=Response(),
        ) as post:
            response = self.client.post("/v1/synthesize", json={"text": "Nat�rlich und klar."})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, wav_data)
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/audio/speech")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gpt-4o-mini-tts")
        self.assertEqual(post.call_args.kwargs["json"]["voice"], "coral")
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], "wav")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-openai-key")

    def test_cloud_voice_health_fails_closed_without_matching_key(self):
        for provider, engine in (("gemini", "gemini"), ("openai_api", "openai")):
            with self.subTest(provider=provider), patch.dict("os.environ", {
                "MICA_TTS_ENGINE": "auto", "MICA_LLM_PROVIDER": provider,
            }, clear=True):
                self.assertEqual(self.client.get("/health").json(), {
                    "status": "key-missing",
                    "engine": engine,
                    "voice": "Sulafat" if engine == "gemini" else "coral",
                })


if __name__ == "__main__":
    unittest.main()
