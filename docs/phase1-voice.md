# Phase 1 voice

MICA uses one fixed local voice whenever the LLM is local. Voice cloning is not
used. The local choice is Kokoro Kerstin; Piper Dii remains an explicit
lightweight fallback and Qwen3-TTS is an audition-only quality comparison.
When the operator explicitly selects a cloud LLM, `auto` uses that same
provider's speech service: Gemini TTS `Sulafat` or OpenAI Speech `coral`.

## Fixed voice

- Engine: Kokoro 82M / StyleTTS2, runtime `kokoro==0.9.4`
- Voice: `df_kerstin`, native German female voice
- Output: 24,000 Hz mono PCM
- Runtime: local CPU inference; no GPU or network required after download
- Base revision: `f3ff3571791e39611d31c381e3a41a3af07b4987`
- Voice revision: `1979d9ef12aff18b3c77cd19a52926ae85c661d3`
- License: Apache-2.0; Kerstin training dataset: CC0-1.0
- Base SHA-256: `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4`
- Config SHA-256: `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f`
- Voice SHA-256: `4f77aed240aaad3eace1b0e9c10394ee4c4774997f729816b39944534656b988`
- Sources: <https://huggingface.co/hexgrad/Kokoro-82M> and
  <https://huggingface.co/cryptomilk/kokoro-german-kerstin>

The published Kokoro runtime does not yet list German even though the German
voice card uses `lang_code="d"`. MICA registers only that documented German
espeak-ng route locally; it does not alter model weights or train a derivative.
The real service path is covered by a regression test and the downloaded model
was also synthesized directly in offline mode.

## Measured local comparison

All figures below are from this Windows PC on 14 September 2026. Perceived
naturalness still requires listening; runtime measurements alone do not prove
that a voice sounds better.

| Model | Role | Audio | Generation | Real-time factor | Notes |
|---|---|---:|---:|---:|---|
| Kokoro `df_kerstin` | fixed voice | 11.12 s | 4.00 s CPU | 0.36 | native German female, Apache-2.0 |
| Qwen3-TTS 0.6B `Serena` | audition only | 11.76 s | 58.17 s CPU | 4.95 | more expressive, but preset is natively Chinese |
| Piper `dii_de-DE` | fallback | verified | faster than real time | n/a | light, but restrictive CC BY-NC-ND 4.0 |

Qwen3-TTS supports German, style instructions and fixed preset voices without
requiring reference audio. Serena is warm and female, but Qwen recommends each
preset's native language for best quality. It is therefore not the default
until the German accent and GPU latency have both passed acceptance. Its model
files stay outside the production image.

## Samples

- `.mica-data/workspace/artifacts/phase1-voice-samples/kokoro-df_kerstin.wav`
  - SHA-256: `bad1961d391ed5c8c283c8eb53235766ed2eab35858c643f57409b4a3d2b0af3`
  - 11.12 seconds, mono PCM, 16 bit, 24,000 Hz
- `.mica-data/workspace/artifacts/phase1-voice-samples/qwen3-serena-de.wav`
  - SHA-256: `fad17ac16eafcfe529f869a179013d7e8304cf7e631472435e141260e5ba88b1`
  - 11.76 seconds, mono PCM, 16 bit, 24,000 Hz
- `.mica-data/workspace/artifacts/phase1-voice-samples/dii_de-DE.wav`
  - SHA-256: `d3ec199ddfe23e6256bd8dd1ea7a6a31bedd3a38ae0ecacccd793441b7243c7`
  - 65.67 seconds, mono PCM, 16 bit, 22,050 Hz

The short comparison text covers a normal sentence, a number, umlauts and `�`.
The longer Dii acceptance sample additionally covers dates, times, punctuation
and long-form output. The user must listen before final physical acceptance.

## Runtime rule

`MICA_TTS_ENGINE=auto` is the normal configuration. It maps `gemini` to Gemini
TTS, `openai_api` to OpenAI Speech, and every local provider to Kokoro. It never
changes `MICA_LLM_PROVIDER` and never activates cloud use from key presence.
Set `kokoro` for an explicit local-only override or `piper` for Dii. Missing
keys/models fail closed; input text and generated audio are never logged.
