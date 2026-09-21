# Phase 0 local models

This directory contains the local-only Phase 0 model payloads. Large binaries
are intentionally ignored by Git. `provenance.json` pins their source revision,
license and verified SHA-256 value.

Required files:

- `Qwen3-4B-Q4_K_M.gguf`
- `ggml-small.bin`
- `dii_de-DE.onnx`
- `dii_de-DE.onnx.json`

Do not replace a file without updating and re-verifying `provenance.json`.
The older Thorsten and Kerstin models may remain on an existing host for
comparison or Phase 0 evidence, but the fixed Phase 1 runtime voice is Dii.
The Dii voice is licensed CC BY-NC-ND 4.0: local non-commercial use is allowed,
attribution to TigreGotico Lda is required, and the model must not be modified
or used to create derivative voices.
