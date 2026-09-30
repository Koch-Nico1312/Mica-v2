# MICA documentation

Documentation index for the repository as of 2026-09-30. The root
[`readme.md`](../readme.md) gives the short introduction; this page points to
the operational and acceptance detail.

## Start here

- [Project overview](Projekt-Übersicht.md): runtimes, capabilities, and setup boundaries.
- [Architecture](Architektur.md): current desktop/backend layout, data flow, and trust boundaries.
- [Backend deployment](../backend/README.md): Windows, ZimaOS, Proxmox VM, preflight, backup, and deployment checks.
- [Backend implementation audit](../backend/IMPLEMENTATION_STATUS.md): dated evidence snapshot and target-host work that remains. Treat its results as historical evidence for the date shown, not as proof of a currently running deployment.
- [Dream-RSI and Laya](dream-rsi.md): optional self-improvement evaluation and local semantic scoring.
- [Hindsight memory](hindsight.md): optional backend memory, source selection, explicit reflection, setup, API, and backup boundaries.
- [Self-source access](self-source-access.md): MICA's constrained access to its own source.
- [Advanced agents](ADVANCED_AGENTS.md): legacy desktop agent components where still applicable; the current runtime boundaries are described in [Architecture](Architektur.md).

## Phasen und Abnahme

These documents distinguish implemented code, automated checks, local runtime
evidence, and acceptance that still requires a target machine or external
service. A feature flag being present or enabled is not deployment proof.

- [Phase 0: local core](phase0-acceptance.md)
- [Phase 1: voice](phase1-acceptance.md) and [voice policy](phase1-voice.md)
- [Phase 2: learning and research](phase2-acceptance.md) and [operating guide](phase2-learning.md)
- [Phase 3A: automation](phase3a-acceptance.md)
- [Phase 4: bounded planning and server operations](phase4-acceptance.md)
- [Phase 4.5: perception and presence](phase4.5-acceptance.md)
- [Hindsight CPU pilot, 2026-09-30](../artifacts/hindsight-pilot/acceptance.md): real-server storage, retrieval, reflection, outage, restart, correction, and deletion checks; three-example quality and latency comparison. Default activation remains off.

The acceptance pages are snapshots and may describe work performed on a
particular machine. Re-run their stated checks against the intended deployment
before treating a gate as passed.

## Design and change records

- [Cloud-provider security](cloud-provider-security.md)
- [Monthly security review](monthly-security-review.md)
- [Architecture decision: Phase 0 local core](decisions/0001-phase0-local-core.md)
- [Dream-RSI decisions and implementation](decisions/20.09.26-100-points-decisions.md), [implementation record](20.09.26-100-points-implementation.md), and [analysis](decisions/20.09.26-100-points-analysis.md)
- [50-point decisions](decisions/20.09.26-50-points-decisions.md) and [implementation record](20.09.26-50-points-implementation.md)
- [Git preparation](Git-Vorbereitung.md)

Older dated change records are retained as history. For current behavior, prefer
the source files and the operational guides linked above.
