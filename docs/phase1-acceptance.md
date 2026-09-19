# Phase 1 acceptance record

This record separates the completed local implementation from checks that need
the user's hearing, the production microphone/speakers or several real usage
days. Phase 1 is not complete while an item below remains unchecked.

## Automated and reproducible evidence

- [x] One immutable, versioned MICA persona is shared by text and voice.
- [x] Invalid persona data and conversation modes fall back to persona v1 and
  `personal`.
- [x] `personal`, `technical` and `monitoring` change focus and response length,
  but preserve MICA's identity and character.
- [x] The allowlisted personal profile is a separate local JSON file; profile
  values are not written to audit events.
- [x] Text chat, turns, PyQt, PWA and voice sessions carry the same normalized
  `conversation_mode`.
- [x] Kokoro `df_kerstin` is the single configured local female voice. Model,
  config, revision, license and SHA-256 values are recorded in
  `models/provenance.json` and `docs/phase1-voice.md`.
- [x] `MICA_TTS_ENGINE=auto` keeps local models on Kokoro and pairs explicitly
  selected Gemini/OpenAI LLM use with the same provider's speech service.
  Mocked tests require no real keys; live cloud voice checks remain optional.
- [x] Real local synthesis produced 24,000 Hz mono WAV audio containing normal
  sentences, numbers and umlauts, faster than real time on the CPU. Piper Dii
  remains a tested explicit fallback.
- [x] The full existing test suite is green, including Phase 0, API, voice, HUD,
  profile, persona and provider-security coverage.
- [x] The Notion Roadmap was fetched after the targeted edit; exactly one Phase
  1 section exists and the surrounding Phase 0 and Phase 2 sections matched
  their pre-edit content.

## Human and production evidence still required

- [ ] Compare `kokoro-df_kerstin.wav`, `qwen3-serena-de.wav` and `dii_de-DE.wav`
  in `artifacts/phase1-voice-samples` and confirm that Kokoro Kerstin should
  remain MICA's fixed voice.
- [ ] Complete the still-open Phase 0 physical voice checks in
  `docs/phase0-acceptance.md`, especially 20/20 push-to-talk sentences and
  20/20 TTS interruption trials.
- [ ] Complete seven consecutive safe everyday-use days for the Phase-0 gate.
  On at least three of those days, use text and voice, restart MICA once, and
  exercise all three modes.
- [ ] Confirm after the final day that no persona drift, unintended profile
  disclosure, lost profile data or critical voice defect occurred.

## Everyday-use log

Record exactly one append-only entry per local calendar day with
`tests/manual_everyday_acceptance.py`. The tool refuses overwrites and reports
both the seven-day Phase-0 gate and the three full Phase-1 days. It stores no
prompts, replies, profile values or audio. Example for a fully exercised day:

```powershell
.\.venv-local\Scripts\python.exe tests\manual_everyday_acceptance.py --text --voice --restart --mode personal --mode technical --mode monitoring --persona-ok --profile-ok --profile-private --no-data-loss --no-unauthorized-action --no-critical-defect
```

The authoritative log is `artifacts/phase1-everyday-use.jsonl`.

Optional OpenAI or Gemini use is not a Phase 1 completion requirement. A live
provider smoke test requires an explicitly supplied key and must not contain
private profile or Brain content. Ollama remains the default.
