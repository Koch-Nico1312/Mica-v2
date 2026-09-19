# Hey Mica wake-word model acceptance

Phase 0 uses an operator-provided ONNX model at the path in
`MICA_WAKE_WORD_MODEL`. No model binary is bundled or silently downloaded.

Before enabling `MICA_WAKE_WORD_ENABLED=true`, record here:

- training source and consent;
- model producer and exact version/commit;
- model SHA-256;
- dataset split used for acceptance;
- license and redistribution terms;
- configured threshold, VAD threshold, cooldown and microphone device;
- result of 40 controlled utterances (minimum 38 detections);
- result of eight hours representative background audio (maximum one false activation).

The model is accepted only when every field above is filled and both thresholds
pass. Audio used for verification must stay local and must not be committed.

Runtime variables are `MICA_WAKE_WORD_DEVICE` (sounddevice index or exact
device name), `MICA_WAKE_WORD_THRESHOLD` (default `0.5`),
`MICA_WAKE_WORD_VAD_THRESHOLD` (default `0.5`) and
`MICA_WAKE_WORD_COOLDOWN_SECONDS` (default `3`). The optional
`MICA_WAKE_WORD_PROVENANCE` points to the JSON acceptance record; otherwise
MICA expects `<model>.provenance.json` next to the ONNX file.

Minimum provenance record:

```json
{
  "source": "consented local training source",
  "version": "exact model version",
  "license": "usage terms",
  "test_dataset": "held-out local dataset identifier",
  "sha256": "model file SHA-256",
  "acceptance": {
    "utterances": 40,
    "detections": 38,
    "background_hours": 8,
    "false_activations": 1
  }
}
```

The runtime remains disabled if the record is missing, the hash differs or an
acceptance threshold is not met.
