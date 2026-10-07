# MICA V2

MICA V2 is a local-first assistant with a Windows desktop interface and a
separately deployed local API/runtime. The desktop app handles chat, voice, and
the HUD; the backend provides the API, local model services, Brain, guarded tool
broker, scheduler, and browser interface. Cloud providers and external
connectors are opt-in.

Local speech recognition defaults to [Parakeet Redux on CPU](docs/parakeet-redux.md).
The model is included when building the STT image; Whisper remains an explicit
alternative. Native Windows CPU support is currently unverified for this model.

The desktop [voice setup](docs/voice-improvements.md) adds microphone calibration,
an adjustable end-of-speech pause, a local names dictionary, speaking to interrupt,
and transient speech diagnostics.
The [conversation and document workflow](docs/dialog-improvements.md) shares
context between text and speech, asks targeted clarification questions, handles
simple commands without the language model and reads selected PDFs, text files
and screenshot text locally.
The [daily assistance tools](docs/daily-assistance.md) verify application windows,
correct timers, offer document reloads, run a reviewed work routine and read
one explicitly selected window through local OCR.
The [productivity extensions](docs/productivity-extensions.md) add explicitly
saved work checkpoints, selected-text previews through a global shortcut,
restart-safe timers, named routines with documents, a daily overview and
confirmed conversational preferences.

> Deployment status: code and local acceptance checks do not prove that a
> particular Windows, ZimaOS, or Proxmox installation is ready. Target-host,
> hardware, certificate, model, and provider checks are listed in the
> [acceptance documentation](docs/README.md).

## Repository layout

| Path | Purpose |
|---|---|
| `desktop/` | Windows PyQt app, local API client, audio, actions, and UI assets |
| `backend/` | FastAPI services, Docker Compose deployment, local model services, tool broker, scheduler, and optional Windows host agent |
| `mica_shared/` | Shared capability, voice-addressing and file-path contracts |
| `legacy/` | Archived Gemini Live runtime/plugins/dashboard and historical tests; excluded from normal checks and images |
| `.mica-data/` | Private local runtime state for the desktop installation; excluded from Git |
| `docs/` | Setup, architecture, feature, security, and acceptance documentation |
| `scripts/` | Repository consistency and documentation checks |
| `tests/`, `backend/tests/` | Automated checks; passing tests do not replace target-host acceptance |

The desktop and backend are distinct runtimes. Desktop `core/` modules are not
the backend's `services/common/` modules.

## Windows desktop

The desktop launcher sets up its pinned Python 3.13 environment and opens the
PyQt application:

```powershell
.\install_and_start.ps1
```

Use `Start MICA.cmd` for the complete local start by double-click. It starts
Docker Desktop when needed, prepares missing local access credentials in Windows
Credential Manager, starts the configured backend services, verifies the HTTPS
connection, and then opens `desktop/local_main.py` with the same `python` from
PATH used by the manual PowerShell command. Existing models in `desktop/models`
are reused through `MICA_MODELS_DIR`; the first start may build/download service
images. Configured Hindsight and the existing Windows host-agent allowlist are
preserved. Optional integrations still require their own setup and credentials.

The starter shows progress in a separate window while Docker, credentials,
services/models and the verified HTTPS connection are prepared. Failed starts
offer retry and access to Docker Desktop or the backend setup directory. If the
Core is reachable but Phase-0 checks report blocked capabilities, the window
shows the restriction and lets you explicitly open MICA to inspect diagnostics.
`python -m desktop.start_mica --console` keeps the console-only start available.
The startup window does not certify physical microphone or speaker readiness.

The previous remote and platform automation configuration have been removed.
Previous Git metadata, including the historical source snapshot's repository,
is archived outside this project. The project now has an empty local repository
on `main`, with no commits or remotes. Current source files and local installation
data are retained. Source updates require a deliberately configured upstream. See
[project preparation](docs/Git-Vorbereitung.md).

Run `install_and_start.ps1` for desktop dependency setup or updates. Its
automatic source update requires a clean checkout and a verified recovery
checkpoint for the current commit, at most 24 hours old. Create it in
`Betrieb` -> `Backup` -> `Update-Sicherung erstellen` after unlocking backup
access. Missing or invalid checkpoints skip the update without preventing
startup. The checkpoint includes data and committed source history, not the
Python environment, models or Windows Credential Manager secrets.
The `-NoUpdate` option skips checking upstream;
`-SetupOnly` prepares and checks the desktop installation
without opening the app. The desktop client expects the backend at
`https://mica.local` by default. Set `MICA_CORE_URL` and, when needed,
`MICA_CORE_CA_FILE` for another local HTTPS endpoint when starting the UI
manually. The complete local starter derives both from `backend/.env` and
uses Caddy's local CA directly, without disabling certificate verification.

## Local backend

The supported container workflow uses Docker Compose. Begin with
[`backend/README.md`](backend/README.md), which covers Windows, ZimaOS,
Proxmox VM, and the constrained CPU-only LXC option. In brief:

1. Copy `backend/.env.example` to `backend/.env`; set the persistent data path,
   local model filenames and HTTPS origin. Configure the API/approval secrets
   and browser password hash using [API and LAN access](docs/api-access.md).
2. Place the required local LLM, Whisper, and TTS model files under the
   configured data directory, then run the documented preflight checks.
3. On Windows, configure the allowed Credential Manager names and start the
   stack through `python -m backend.windows_launcher`. On Linux, use the
   documented `docker compose` commands.
4. Confirm the post-start health and HTTPS checks before connecting the
   desktop app or exposing the PWA on a LAN.

The Compose stack keeps model containers and the broker off the Docker socket.
Native host actions, when configured, run in the separate mTLS-protected host
agent. The broker applies capability checks, approvals, audit, and emergency
stop before dispatch.

## Optional capabilities

Optional features remain off unless explicitly enabled. Phase 2 research,
Phase 3 automation, Phase 4 planning/server functions, Dream-RSI, Laya,
self-editing, native CUA, and external connectors have separate gates. Read
each feature's setup and acceptance page before enabling it. Laya is an
optional local semantic scorer; it advises ranking and signal triage and does
not grant permissions or execute actions. See
[`docs/dream-rsi.md`](docs/dream-rsi.md).

Hindsight optionally adds long-term memory for selected short conversation
excerpts and task reports. Markdown remains authoritative; exact local search
matches keep priority, and the local search remains available during outages.
Explicit reflection is marked as an unconfirmed inference with sources.
Enable it separately using the [Hindsight guide](docs/hindsight.md).

The [local CPU pilot on 2026-09-30](artifacts/hindsight-pilot/acceptance.md)
verified storage, retrieval, reflection, outage recovery, restart, correction,
and deletion with a real server. Its three examples showed no retrieval quality
gain over local search; reflection took about 131 seconds. Hindsight remains
disabled by default. This pilot does not establish general quality or
production readiness.

Provider secrets must not be placed in committed files. The backend Windows
launcher reads only configured secret names from Windows Credential Manager
and passes their values to the Compose process environment. Cloud use and
private-context transfer require explicit configuration.

## Documentation

- [Documentation index and acceptance status](docs/README.md)
- [Project overview](docs/Projekt-Übersicht.md)
- [Current architecture and trust boundaries](docs/Architektur.md)
- [Backend deployment and target-host checks](backend/README.md)
- [Dream-RSI and optional Laya scoring](docs/dream-rsi.md)
- [Self-source access](docs/self-source-access.md)
- [Voice policy](docs/phase1-voice.md)
- [Research and learning](docs/phase2-learning.md)
- [Optional Hindsight memory: setup, API, and backup boundaries](docs/hindsight.md)
- [Hindsight pilot results and measurements](artifacts/hindsight-pilot/acceptance.md)
- [Phase 0–4.5 acceptance documents](docs/README.md#phasen-und-abnahme)

For development checks, use the commands documented by the relevant project
area. A passing unit test confirms only the exercised code path; it does not
prove deployment health, physical microphone behavior, external-provider
connectivity, or target-host safety.

See [repository maintenance](docs/repository-maintenance.md) for the complete
local check commands and the distinction between source, runtime data, and
historical evidence.
The [code efficiency record](docs/code-efficiency.md) describes incremental
indexing, batched database reads, bounded audit memory, UI changes and repeatable
local benchmarks.

## License

See [LICENSE](LICENSE).


## Lernen und Weiterentwicklung

Der lokale Bereich **Weiterentwicklung** verbindet bestätigte Vorlieben, erkannte Fähigkeitslücken, eine Skill-Werkstatt mit unabhängigen Qualitätsvergleichen und begrenzte Reparaturen versionierter Code-Artefakte. Nutzung, Grenzen und API stehen in [Lernen und Weiterentwicklung](docs/evolution.md).
