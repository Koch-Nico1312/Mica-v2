# Phase 0 acceptance record

This file separates implemented controls from evidence that must be collected
on the production Windows PC. Phase 0 is not complete until every unchecked
item has current evidence.

## Automated controls

- [x] PyQt production entry point uses the local core client.
- [x] Push-to-talk uses press/release and 16 kHz mono in-memory PCM.
- [x] Twenty capability manifests use one policy/broker/host boundary.
- [x] Internet-capable tools default to disabled.
- [x] Exact voice/text emergency phrase and durable host stop exist.
- [x] Audit redacts credentials and sensitive request fields.
- [x] Request/token quantities and unknown-price behavior are versioned.
- [x] Backup restore and Markdown-only index rebuild have automated tests.
- [x] Dependencies are pinned and monthly updates arrive only as review PRs;
  production updates remain manual and owner-approved.
- [x] Every allowed operation exposes an explicit risk class. A shared matrix
  runs schema, unavailable-host, dry-run, approval/rejection, Not-Aus,
  retry/idempotency and secret-redaction checks for all 20 capabilities.
- [x] Non-dry-run dispatch is blocked before the broker unless the fresh
  Windows preflight, including encryption and backup checks, is fully green.
- [x] Legacy `web_search` operations that would invoke Gemini are unavailable;
  internally fixed network destinations must match the operator allowlist.
- [x] Wake-word activation requires a matching model hash, provenance/license
  record and recorded 38/40 plus eight-hour acceptance thresholds.

## Production evidence still required

- [ ] Windows preflight is fully green with Docker Desktop running.
- [x] Qwen, whisper.cpp and Piper files have pinned provenance and verified
  SHA-256 values; all seven local Core containers became healthy and the real
  `/v1/turns` path returned `Mica lokal bereit`. See
  `models/provenance.json` and `artifacts/phase0-local-core-current.json`.
- [ ] Data and real backup target are confirmed BitLocker-protected.
- [x] Local broker-to-agent mTLS accepts the generated client identity and
  rejects a connection without it; see `artifacts/phase0-mtls-current.json`.
  The probe ran through `host.docker.internal:9443` and an actual
  `system_status` dispatch also succeeded.
- [ ] Firewall evidence shows port 9443 reachable only from the Docker subnet.
- [ ] All enabled provider credentials reside in Windows Credential Manager.
- [ ] Push-to-talk passes 20/20 controlled sentences.
- [ ] Escape interrupts TTS within 200 ms in 20/20 trials.
- [ ] Hey Mica passes at least 38/40 detections and at most one false activation
  in eight hours; model provenance and license are recorded.
- [ ] Every one of the 20 modules passes its schema, happy path, missing
  dependency, dry-run, approval/rejection, stop, retry/idempotency and log
  redaction matrix in staging. The shared safety matrix is green for all 20;
  real adapter happy paths and third-party dependency cases remain pending.
- [ ] Encrypted backup is restored to a fresh directory and its hash chain and
  Markdown-only rebuilt index are verified.
- [ ] Emergency stop is exercised during file, browser and test-process work,
  survives restart and blocks all new actions. The real test-process case is
  green, including process-tree termination and restart persistence; see
  `artifacts/phase0-emergency-process-current.json`. File and browser cases are
  still pending.
- [ ] Cleanup absence tests pass for QR pairing, marketplace, publishing,
  multi-tenant ACL and direct production Gemini/action dispatch.
- [ ] Seven consecutive real usage days complete without data loss,
  unauthorized action or open critical defect.

## Reproducible physical evidence

Run these on the production Windows PC. They never store microphone PCM:

```powershell
.\.venv-local\Scripts\python.exe tests\manual_voice_acceptance.py ptt
.\.venv-local\Scripts\python.exe tests\manual_voice_acceptance.py interrupt
.\.venv-local\Scripts\python.exe tests\manual_wake_word_acceptance.py detections --model C:\path\to\hey-mica.onnx
.\.venv-local\Scripts\python.exe tests\manual_wake_word_acceptance.py background --model C:\path\to\hey-mica.onnx --hours 8
```

The first two update `artifacts/phase0-voice-acceptance-current.json`; the wake
tests update `artifacts/phase0-wake-word-acceptance-current.json`. A candidate
ONNX model must be supplied locally by the operator. Production wake-word
startup remains blocked until both wake thresholds and provenance are recorded.
