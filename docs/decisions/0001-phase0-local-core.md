# ADR-0001: One local core and a scoped Windows action boundary

- Status: accepted
- Date: 2026-09-10

## Decision

The PyQt HUD is the primary client and communicates only with the local HTTPS
MICA API. Text, voice, retrieval, policy, approvals and audit share that API.
Native PC actions cross the broker and a separately deployed Windows host
agent over mTLS. The agent exposes exact capability names, never shell text or
model-selected imports, and runs each request in a bounded child process.

Networked capabilities and Windows execution are opt-in per capability. Legacy
branches that instantiate a hosted model are reported unavailable until they
have a local replacement. The PWA remains a local owner fallback.

## Consequences

The assistant can remain useful for local chat while readiness is degraded,
but production action mode stays blocked until Docker, models, certificates,
BitLocker, backup and the Windows agent pass preflight. Saved reversible scopes
remain parameter-bound; destructive work uses single-use approval and an
idempotency key. Emergency stop is durable and remote resume is disabled by
default.
