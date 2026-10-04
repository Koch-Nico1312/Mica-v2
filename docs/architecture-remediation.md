# Architecture remediation — 2026-10-02

The seven findings in the goal objective are addressed in the working tree.
Pre-existing changes are preserved. This record describes implementation and
local verification; target-host, hardware and production acceptance remain
separate checks.

## Requirements and resulting behavior

| Finding | Result | Verification |
|---|---|---|
| UI/API monoliths and duplicate logic | UI support, theme, widgets, appearance, settings and auxiliary panels have separate modules. Toggle styling is shared. API schemas, gates, route binding, service construction and fourteen domain routers are separate; `app.py` is the composition root. | Existing UI/API behavior checks; simultaneous independent factory instances, private Brain/state isolation and injected completions; factory import creates no runtime files. |
| Runtime cycle and duplicate module identities | `mica_shared` owns capabilities, addressability and file paths. Host history never imports action adapters. Active imports use `desktop.*`, `backend.*` and `mica_shared.*`. Addressing has one import path and class identity. | Shared file/receipt equivalence, fresh-process history import, AST boundary checks, class identity assertions and Python image-layout imports without desktop or `services` aliases. |
| Parallel Gemini Live runtime | Main entry point, bundled plugins, phone dashboard and ten unused core modules are preserved under `legacy/gemini_live`. Inactive-only tests are archived; active native actions and feature dependencies remain. Shortcut/autostart launch `local_main.py`. Project inspection no longer discovers bundled plugins. | Active full suite; normal imports cannot reference `legacy`; native project inspection fails the regression check if it discovers bundled plugins. Assertion-free timing demos are excluded from collection. |
| Unauthenticated API/LAN surface | API-token guard runs before HTTP handlers and WebSocket acceptance. Caddy requires browser login or a native token. Browser proxy supplies the token; native HTTP/voice share the configured credential. Action approvals and provider signatures remain additional guards. | Anonymous checks enumerate sensitive routes, docs and unknown paths; missing/incorrect/ambiguous credentials and WebSockets fail closed; approval/provider checks remain effective. Actual local trusted HTTPS Caddy requests exercise browser/native ingress. |
| Cloud private-context opt-in | The current conversation path already enforced the flag; `/v1/turns` delegates to it. The boundary is now covered directly rather than inferred from a helper definition. | Eight real outbound-payload regression cases: chat/turns × OpenAI/Gemini × opt-in on/off. Brain, profile, reflections, promoted prompt, runbook and twin markers are absent without opt-in and present with it. |
| Local test configuration | Local checks install dependencies and run the full active suite, coverage, Ruff and strict pip-audit. Pytest includes both test roots, strict markers and per-test timeouts. Evidence is saved locally. Installer bootstrap is upgraded past the known pip advisory. | Identical requirements installed successfully with pip into a fresh Python 3.13 environment outside the checkout. Full suite, Ruff, dependency consistency and strict audit checked locally. |
| Corrupt environment example | Removed concatenation marker, fake credential assignments and unused assistant/plugin variables. Kept `MICA_LLM_URL` because the active direct LLM client consumes it; normal Core transport is explicitly HTTPS. | Template/runtime-consumer review and existing configuration/client checks. New mandatory API/LAN credentials are documented in `api-access.md`. |

## Packaging, cache and preservation

Python service images build from the repository root, copying only backend
services, the backup module, web UI and `mica_shared`. The root `.dockerignore`
is default-deny. Separate STT/TTS contexts also exclude deployment configuration
and state. Main and Hindsight Compose configurations validate using disposable
configuration. Direct preflight and backup CLI help entry points run.

The old `.uv-cache` directory is gone from the checkout. The desktop launcher
defaults new cache writes to `%LOCALAPPDATA%/uv/cache`, while preserving an
explicit owner setting. All four existing project virtual
environments and the historical source snapshot remain in place, including its
local Git metadata. Ignored
credentials and production data were not modified.

## Evidence and limits

The final fresh-install active suite passes: **516 tests and 77 subtests**, with
**62% aggregate coverage** over `desktop`, `backend` and `mica_shared`.
Ruff's execution-defect rules, dependency consistency, strict pip-audit and
diff whitespace checks pass. The previous inactive-only cases are retained
in `legacy/tests/`, which explains the reduced normal-suite count.

Strict auditing first exposed three urllib3 2.7.0 advisories. Runtime requirements
now require urllib3 >=2.8; the Windows lockfiles were regenerated and verified.
Fresh-environment auditing additionally exposed the bundled pip 26.1.2 advisory;
Development setup upgrades pip to >=26.2 before installation, and requirements
carry the same floor. The subsequent strict audit found no known vulnerabilities.

The coverage runs emit an upstream TestClient deprecation and SQLite resource
warnings during fixture lifecycle/garbage collection; they do not fail tests.
They are recorded here rather than presenting the run as warning-free.

A final real local Uvicorn factory process answered health (200), rejected
anonymous API access (401) and accepted the disposable API token (200). Caddy 2.11.4
validated and served HTTPS using a disposable CA, credentials and upstream;
anonymous/incorrect credentials were rejected and authenticated browser/native
requests forwarded correctly. Python image-layout imports are verified in a
fresh process, and Compose configuration is validated.

The Docker daemon was unavailable, so the configured Caddy 2.8 image and full
container stack have not been built/run here. Automated remote checks are not
configured for this fresh local project. Physical audio, target-host certificates/firewall,
models and real cloud/provider acceptance were not performed by these checks.

See [API and LAN access](api-access.md), [architecture](Architektur.md),
[archived runtime](../legacy/README.md) and [monthly security review](monthly-security-review.md).
