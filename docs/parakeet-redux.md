# Local speech recognition: Parakeet Redux

MICA's STT service defaults to `moondream/parakeet-redux` with Photon on the
CPU. The existing desktop and browser transport still sends raw 16 kHz mono
signed little-endian int16 PCM to `POST /v1/transcribe`; the response stays
`{"text": "..."}`. Recognition happens after the recording ends. No audio is
stored or sent to a cloud transcription provider.

The service keeps one resident model, serializes inference, and runs blocking
recognition outside the HTTP event loop. It bounds uploads while reading,
rejects incomplete PCM samples, and reports unavailable models as HTTP 503.
The health endpoint only reports `ok` after a real startup inference succeeds.
Language is detected automatically; Redux does not accept a forced `de` flag.

## Docker setup

Build and restart the STT service from `backend/`:

```sh
docker compose --env-file .env up -d --build --no-deps stt
```

The image installs the separate `requirements-stt.txt` runtime and downloads
model weights during the build, which requires internet access. At runtime
Hugging Face is offline and STT remains on the private Compose network. The
model cache is included in the image at `/opt/mica-models/huggingface`;
the `/models` mount is only needed for the explicit Whisper alternative.
No NVIDIA device reservation is used by STT. Downloaded weights are about
178 MB; installed dependencies and working memory are larger.

Existing configurations without `MICA_STT_ENGINE` use Redux. Explicitly set
`MICA_STT_ENGINE=parakeet-redux` when migrating a configured Whisper setup.

## Explicit Whisper alternative

Set both variables in `backend/.env` and rebuild STT:

```dotenv
MICA_STT_ENGINE=whisper.cpp
MICA_STT_DOCKERFILE=docker/Dockerfile.stt-whisper
WHISPER_MODEL=ggml-small.bin
WHISPER_LANGUAGE=de
```

Mount the Whisper model in the existing model directory. There is no automatic
engine switch or cloud fallback when Redux initialization fails.

## Windows and verification

The isolated `.venv-parakeet` environment does not modify MICA's desktop/API
dependencies. On this Ryzen 7 7800X3D, the native Windows Photon 2.6.1 runtime
reported the CPU kernel path as `scalar` and refused to load ternary weights.
Use the Linux Docker service; native Windows CPU support is not established.

On 2026-10-05, the same STT service passed an offline CPU runtime test under
Ubuntu WSL2 on this machine. Startup including real warm-up took 6.01 seconds;
5.82 seconds of synthetic German speech took 0.182 seconds to transcribe via
`POST /v1/transcribe`, returning HTTP 200. The transcript was
`Hallo Maika. Öffne meine Notizen und erinnere mich morgen um 8 Uhr.`
The spoken name `Mica` was misrecognized as `Maika`. This is one synthetic
sample, not a microphone/dialect benchmark. See the
[recorded result](../artifacts/parakeet-redux/runtime.json).

Sixteen focused STT, deployment-contract and preflight tests passed, including
four preflight subtests. Compose configuration validation also passed.

The Docker build and live STT deployment were subsequently verified on
2026-10-05. `mica-stt-1` is healthy in the private `mica_mica-internal` network
(Docker `Internal=true`), with no GPU device reservation, CPU-only Torch and
`HF_HUB_OFFLINE=1`. The same 5.82-second synthetic recording returned HTTP 200
in 0.229 seconds via the running service; empty and malformed PCM returned
HTTP 413 and 422. See [Docker runtime evidence](../artifacts/parakeet-redux/docker-runtime.json).
This verifies the live STT service, not physical microphone/dialect quality or
an entire desktop-to-speaker conversation.

Docker initially failed on a stale `docker-secrets-engine/engine.sock` reparse
point. The temporary directory was recoverably renamed to
`docker-secrets-engine.parakeet-backup-20261005-170429` under Windows
`AppData/Local`, then Docker was restarted. No volumes or model data were deleted.
The previous STT image is retained as `mica-stt:before-parakeet-20261005`.

Tests cover PCM conversion, transport compatibility, size bounds, malformed
input, unavailable models, inference errors, startup readiness, cleanup and
the explicit Whisper path. They do not establish microphone accuracy or
performance on Austrian dialect. Live progressive preview is not used here.

Redux supports German, but the publisher reports weaker recognition in noise.
Compare recordings from the intended microphone before claiming voice-quality
acceptance. Wake-word recognition, dialogue models and TTS remain separate.

Model weights use CC-BY-4.0: attribute Moondream and NVIDIA and retain the
license when redistributing weights. Runtime package licenses are separate.

Sources: [model card](https://huggingface.co/moondream/parakeet-redux),
[release](https://moondream.ai/blog/introducing-parakeet-redux-and-ultra),
[Python runtime](https://pypi.org/project/moondream/).
