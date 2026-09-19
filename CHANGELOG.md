# Changelog

## 2026-09-10

- Added a native Windows host-agent mTLS path with generated CA/server/client
  identities, strict client authentication, no automatic port-80 redirect and
  a repeatable positive/negative probe.
- Made Not-Aus survive the legacy marker-name migration, cancel active voice
  sessions and fail closed when broker/host recovery is not confirmed.
- Added operation allowlists, local path roots, deterministic flight lookup,
  bounded project inspection and no-persistence screen metadata adapters.
- Added an exact application-name allowlist and removed shell-based Windows
  application launching.
- Pinned and SHA-256-verified Qwen3 4B Q4_K_M, whisper.cpp small and Piper
  Thorsten medium; all seven local Core containers reached healthy state.
- Switched Qwen from raw completion to its chat template with thinking disabled
  and verified the real `/v1/turns` reply `Mica lokal bereit`.
- Fixed German STT to use an explicit `de` language setting and verified a
  local Piper-to-Whisper round trip.
- Added a single table-driven safety matrix covering all 20 capabilities and
  made every allowed operation's risk explicit.
- Blocked non-dry-run dispatch until fresh Windows preflight evidence is fully
  green, and made missing adapter imports fail as `unavailable`.
- Disabled legacy Gemini-backed web-search operations and bound fixed internal
  network destinations to operator allowlists.
- Made Wake-Word activation require hash-matched provenance and the recorded
  40-utterance/eight-hour acceptance thresholds.
- Verified the updated tree with 108 passing tests.

## Unreleased - Phase 0

- Routed the production PyQt client through the local HTTPS core.
- Added local push-to-talk and configurable local wake-word plumbing without
  audio persistence.
- Added versioned capability, execution and voice contracts for all 20 legacy
  action modules.
- Added a deny-by-default Windows host agent with mTLS identity, replay
  protection, parameter-bound approvals, timeouts and persistent emergency
  stop.
- Added per-capability network opt-in, operation-level risks and idempotency.
- Added Windows preflight checks for Docker, models, audio, certificates,
  storage, BitLocker, backup and Credential Manager.
- Added credential storage helpers, audit redaction, operational measurements,
  a versioned price table and hard per-turn execution limits.
- Fixed UTF-8 handling when activating validated improvement artifacts on
  Windows.
