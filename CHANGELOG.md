# Changelog

## 2026-10-04 – Code efficiency refactor

- Incrementally synchronize the derived Brain index, read sources once per
  search, and avoid vector work when exact results already fill the limit.
  Explicit reindex requests still rebuild from Markdown; source writes are atomic.
- Keep research-domain filtering ahead of the FTS limit and preserve source
  order for equal-rank hits.
- Batch plan details and twin facts; index frequently ordered database queries.
- Stream complete audit-chain verification while retaining only the requested
  tail, and count removed memory entries without repeatedly serializing the store.
- Separate local desktop pages, share page headers, pause hidden decorative
  animations, and use a constant-time FIFO for typed log messages.
- Remove unused implementation imports and optional dependency probes; use
  canonical desktop configuration/control-center imports and verify them in CI.
- Add behavior/recovery regressions and a repeatable temporary-data benchmark.

## 2026-10-04 – Repository cleanup

- Restored canonical root filenames from identical Explorer copies and
  archived redundant local copies outside the checkout without discarding data.
- Moved historical design QA into `docs/` and aligned current startup guides.
- Replaced the obsolete Git migration walkthrough with current review guidance.
- Added a read-only repository checker for required files, Python syntax and
  local documentation links, and included it in the Windows CI checks.
- Kept the manual Python setup helper import-safe and independent of the
  caller's working directory; protected copied private data from Git tracking.

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
