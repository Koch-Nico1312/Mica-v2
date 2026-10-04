# MICA backend and deployment

The backend is a separate runtime used by the Windows PyQt desktop client and
the browser PWA. Docker Compose provides the API, llama.cpp, whisper.cpp STT,
the TTS service, Markdown Brain indexer, tool broker, scheduler, web UI, and
Caddy HTTPS entry point. The optional fallback profile adds another local
llama.cpp server. The native Windows host agent is deployed separately and
communicates with the broker over mTLS when explicitly configured.

API and voice access require `MICA_API_TOKEN`; the PWA additionally uses the
Caddy browser login. Configure the token and LAN password hash before starting
the updated stack. See [API/LAN access setup](../docs/api-access.md).

## Windows start

Keep real provider values out of `.env`. Copy
`desktop/config/credential-names.example.json` to
`desktop/config/credential-names.json`, store the named values with
`desktop.core.secure_store`, and launch Compose through
`python -m backend.windows_launcher`. This starts Docker Compose (by default
`up -d --build`), reads Windows Credential Manager, and passes allowed values
only to the child process environment. Connector names not in the JSON remain
unset. The desktop UI is started separately with the repository-root
`install_and_start.ps1`; it expects the backend HTTPS endpoint to be reachable.

For the combined local start, double-click `Start MICA.cmd` in the repository
root after installing the Python dependencies. It uses `python` from PATH,
starts Docker Desktop when needed, completes missing local configuration,
starts Compose, checks HTTPS with Caddy's local CA, and opens the desktop UI.
Existing local models can be reused through `MICA_MODELS_DIR` instead of being
copied into the data directory. See the [root startup guide](../readme.md#windows-desktop).

Run the native action service on loopback as described in
`windows_host_agent/README.md`. Its Caddy mTLS listener uses port 9443. Set the
broker URL to `https://host.docker.internal:9443`, then install the reviewed
Windows firewall allow rule with the exact Docker Desktop subnet. Do not guess
the subnet and do not expose the listener to the LAN.

The local operations view is `GET /v1/operations/summary`. It reports measured
requests, llama.cpp token counters, duration, errors, retries, tool readiness
and external calls. The bundled price table is versioned; providers without a
currently verified source show quantities and a null cost rather than an
estimate.

## Optional Hindsight memory

Hindsight adds memory for selected short user excerpts and completed tool
reports. Markdown remains authoritative, exact local matches keep priority,
and outages fall back to local search. Reflection requires an explicit request
and returns an unconfirmed inference with sources. It affects the backend;
the separate desktop JSON memory is unchanged.

Set both options in `backend/.env` to enable private source transfer:

```env
MICA_HINDSIGHT_ENABLED=1
MICA_HINDSIGHT_ALLOW_PRIVATE=1
```

On Windows, start from the repository root through the existing launcher:

```powershell
python -m backend.windows_launcher --hindsight -- up -d --build
```

On Linux, start from `backend/` with the optional Compose override:

```sh
docker compose -f docker-compose.yml -f docker-compose.hindsight.yml --profile hindsight up -d --build
```

The override runs Hindsight 0.10.2 and a dedicated sync worker, using the local
LLM with tool support and a 16384-token context. Hindsight downloads embedding
and reranking models on first start; the production override exposes no host
ports. The source sync ledger lives under `MICA_DATA_DIR/memory-sync/`, while
Hindsight's database and model cache use separate named volumes.

`GET /v1/memory/hindsight` reports local synchronization state, not live service
health. Use `Rückblick: …` in backend chat for explicit reflection. See the
[full guide](../docs/hindsight.md) for selection rules, API access, timeouts,
correction/deletion, disabling, and backup boundaries.

The [2026-09-30 CPU pilot](../artifacts/hindsight-pilot/acceptance.md) verified
real-server retention, recall, reflection, outage recovery, restart, correction,
and deletion. Three examples showed no search quality gain over the local Brain;
reflection took about 131 seconds. Hindsight stays disabled by default.

## Start on ZimaOS

1. Copy `.env.example` to `.env` and set the persistent ZimaOS volume path and
   model filenames. Put Qwen3 GGUF, whisper.cpp `small`, and Piper Thorsten
   medium models below `${MICA_DATA_DIR}/models`.
2. Before starting services, run `python3 preflight.py --data-dir /your/mica-volume
   --gpu-probe --llama-load-test --backup-dir /your/backup-target --backup-drill --strict`
   and save its JSON output with the deployment record. It checks Docker plus
   Compose, mounted-volume writes both on the host and in a temporary container,
   model files, CPU/RAM/free space, Caddy ports, time synchronization, NVIDIA
   runtime/CUDA access, and an actual Markdown/Audit backup followed by a
   disposable restore plus SQLite re-index.
3. Confirm NVIDIA container access and run the preflight/load test before
   increasing `LLAMA_GPU_LAYERS`; the default is deliberately conservative for
   the GTX 970.
4. Run `docker compose --env-file .env up -d --build` from this directory.
5. The included Caddy service is the sole LAN entry point. It routes the PWA
   and WebSocket to the same HTTPS origin; trust its local CA on each PC or
   phone, or replace `tls internal` in `Caddyfile.example` with your LAN
   certificate policy. Set `MICA_PUBLIC_HOST` and
   `MICA_ALLOWED_VOICE_ORIGINS` to that exact HTTPS origin. Do not expose port
   8000 directly.
6. Once Caddy is healthy and the local CA (or your LAN CA) is trusted by the
   host running this check, run `python3 preflight.py --data-dir
   /your/mica-volume --public-url https://mica.local --strict`. This is the
   post-start DNS, HTTPS-certificate, and HTTP-response proof; it cannot pass
   before the service exists.

## Proxmox VE: supported Linux VM path

Use a normal Debian/Ubuntu Linux **VM** for Docker and any NVIDIA workload.
MICA does not use a Proxmox dashboard API, guest-agent command, or host mount:
the same `docker-compose.yml` runs inside the guest and all `MICA_DATA_DIR`
paths are guest-local filesystems. Assign at least 4 vCPU and 16 GiB RAM as a
baseline; select more RAM/VRAM for larger models or contexts. The preflight
enforces these values by default and lets an operator choose stricter values
with `--min-cpu` and `--min-memory-gib`.

For GPU use, complete IOMMU/VFIO and PCI(e) passthrough on the Proxmox host
first, then verify `nvidia-smi` inside the VM. That host-side configuration is
deliberately outside MICA and must follow the current [Proxmox VE
Administration Guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.pdf)
(PCI(e) passthrough). Install Docker Engine and the Compose plugin in the
guest using the current [Docker Engine Debian
instructions](https://docs.docker.com/engine/install/debian/) and [Compose
plugin instructions](https://docs.docker.com/compose/install/linux/). Install
the guest NVIDIA driver and then configure the NVIDIA Container Toolkit for
Docker; NVIDIA documents `nvidia-ctk runtime configure --runtime=docker` and
the Docker restart in its [current installation
guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

Copy `.env.example` to `.env`, set for example
`MICA_DATA_DIR=/srv/mica`, place models below `/srv/mica/models`, and run this
from the MICA directory inside the VM:

```sh
python3 preflight.py --target proxmox-vm --data-dir /srv/mica --gpu-probe --llama-load-test --backup-dir /srv/mica-backup --backup-drill --strict
docker compose --env-file .env up -d --build
python3 preflight.py --target proxmox-vm --data-dir /srv/mica --public-url https://mica.example.lan --strict
```

The first command also runs `docker compose --env-file .env -f
docker-compose.yml config --quiet` when `.env` is present. The second
preflight is intentionally after Caddy has started. Its `https.input`, `dns`,
`time`, `ports`, `resources`, `nvidia_runtime`, and
`nvidia_container_probe` JSON fields distinguish a bad origin, name lookup,
clock, port conflict, insufficient guest sizing, missing runtime, and failed
GPU container. A `permission_unverified` result for ports 80/443 means the
unprivileged probe could not bind a privileged port; it is not evidence that a
port is free, so repeat it with the same privilege that will run Docker or
check the guest's listener/firewall policy.

### Optional Proxmox LXC path (CPU-only, constrained)

An LXC is not the supported MICA GPU path. Docker-in-LXC requires host-admin
choices such as nesting/security profile, storage-driver compatibility and
possibly device mappings; none can be proven safely from inside a guest.
MICA therefore neither supplies Proxmox UI/API automation nor declares an LXC
GPU setup as working. Use it only for a CPU-only trial, accept the constraints
explicitly, and keep the same guest-local persistent volume:

```sh
python3 preflight.py --target proxmox-lxc --acknowledge-lxc-constraints --data-dir /srv/mica --compose-file docker-compose.yml --compose-file docker-compose.lxc.yml --strict
docker compose -f docker-compose.yml -f docker-compose.lxc.yml --env-file .env up -d --build
```

`docker-compose.lxc.yml` uses Docker's documented `!reset` merge tag to remove
the base GPU reservation; run the included Compose-config preflight and update
the Compose plugin if that command rejects the tag. It switches only
`llama-server` to the documented CPU `:server` image and forces zero GPU
layers. Do not enable the `fallback` profile or add
`--gpu-probe`/`--llama-load-test` in this LXC path: the preflight marks a
requested LXC GPU deployment incompatible even if a locally mapped device
happens to be visible. Move GPU workloads to the VM path above.

Regular backend state is below `MICA_DATA_DIR`; optional Hindsight database and
model-cache state lives in separate named volumes. The Docker socket is never
mounted into a model container or the tool broker. Markdown files under
`brain/` are authoritative; `index/brain.sqlite3` can be rebuilt at any time.
The rebuild creates SQLite FTS5 plus a deterministic local token/trigram
vector index without sending notes to an embedding API. If Hindsight is enabled,
only selected short sources are transferred to that configured service, which
uses its own embedding and reranking models.

## Backup and restore acceptance

Markdown below `brain/` and the hash-chained `audit/events.jsonl` are the
backup truth. `index/brain.sqlite3` is intentionally excluded: it is rebuilt
from the restored Markdown during every drill. On the target host, use the
configured persistent backup target (not a temporary container path):

```sh
python3 backup_restore.py --data-dir /your/mica-volume --backup-dir /your/backup-target
```

The drill also exports the Hindsight sync ledger at its standard
`memory-sync/hindsight.sqlite3` path as JSON in `state/phase4.json` and
reconstructs it during restore. It does not back up Hindsight's separate
PostgreSQL or model-cache volumes. Back those up separately when using the
extension; a custom ledger path also needs its own backup arrangement.

This creates a timestamped `mica-truth-*.tar.gz` and a sibling JSON report. It
restores only into a fresh temporary directory, verifies every archived
SHA-256 and the entire audit chain, then rebuilds FTS/vector SQLite there. A
non-zero exit means that archive is not an accepted restore point. To verify a
previous archive without making a new snapshot:

```sh
python3 backup_restore.py --backup-dir /your/backup-target --verify /your/backup-target/mica-truth-....tar.gz
```

`preflight.py --backup-drill` runs the same operation and reports it under
`backup.drill_passed`; `--strict` rejects a supplied backup target unless that
drill has passed. The drill writes only a new archive/report in the backup
target and temporary restore data. It does not replace live files.

Compose starts the API only after its mandatory model, voice, index, broker,
and scheduler dependencies report healthy. HTTP services probe their own
`/health` endpoint. The two worker services instead publish an atomic, fresh
completion marker after each index/scheduling pass; a merely running but
stalled worker becomes unhealthy after 45/75 seconds respectively.

Before a deployment, the configuration contract can be checked without
starting services:

```sh
docker compose --env-file .env config --quiet
python3 -m unittest tests.test_deployment_acceptance -v
```

The first runnable vertical slice is text planning, local Markdown retrieval,
hash-chained audit events, approval-gated tool dispatch, and browser audio
transport. STT uses local whisper.cpp. With `MICA_TTS_ENGINE=auto`, local LLMs
use Kokoro while an explicitly selected Gemini/OpenAI cloud LLM uses the same
provider's speech API. Missing models or matching keys fail closed; there is no
automatic cloud fallback or provider switch.

## Phase-4 pilot: bounded autonomy

Phase 4 reuses the existing policy, broker and scheduler. Enable the master
flag and only the required module flags from `.env.example`; all are off by
default. Agent plans are finite, hashed and dry-run before activation. The
scheduler processes at most one plan step per pass and rechecks emergency stop,
budget, idempotency and exact approval scope every time. Unknown actions, shell
text and dynamic tools are rejected.

The ZimaOS server agent reads only allowlisted targets through the broker. A
monitoring series runs every 300 seconds and is capped at 288 occurrences.
Container lifecycle, prune, network and host changes are never performed by the
scanner and still require a fresh destructive approval. Digital-Twin facts are
stored separately from the confirmed profile and can be explained, changed,
revoked or deleted through `/v1/digital-twin/*`; they cannot alter policy,
approvals, recipients or host targets. The PWA's **Autonomie** page and PyQt HUD
share the same presence vocabulary. See `docs/phase4-acceptance.md` for the
verified local boundary and the remaining real-ZimaOS gates.

## Opt-in connectors

Telegram, WhatsApp, Push and SIP are disabled by default and have no stored
secret. The broker contains protocol-specific adapters for Telegram Bot API,
WhatsApp Cloud API, ntfy-compatible Push and allowlisted Asterisk ARI/SIP calls.
Credentials stay in environment variables. Authenticated inbound webhooks only
create a dry-run plan; they can never execute a model-supplied action directly.
Telegram uses its `X-Telegram-Bot-Api-Secret-Token` on
`POST /v1/connectors/telegram/webhook`; optionally restrict it further with
`MICA_TELEGRAM_INBOUND_CHAT_IDS`. WhatsApp Cloud API verifies its Meta
challenge on `GET /v1/connectors/whatsapp/webhook` using
`MICA_WHATSAPP_VERIFY_TOKEN` and validates every POST's raw-body
`X-Hub-Signature-256` using `MICA_WHATSAPP_APP_SECRET`. Both endpoints reject
requests until the matching connector was explicitly enabled and deduplicate
provider event IDs.
A `message.send` request is always an external, single-use destructive action.
A due scheduled message pauses in `awaiting_approval` and can then be dispatched
through `POST /v1/schedules/{id}/dispatch` with the same browser confirmation.
Schedules may include a finite `recurrence` object with `every_seconds`
(60 to 31,622,400) and `occurrences` (2 to 1,000); unbounded cron expressions
are intentionally unsupported. `reminder.dispatch` uses the same due-message
approval and broker path as `message.send`.

## Browser approvals and emergency stop

Set a long random `MICA_APPROVAL_SECRET`. The PWA exchanges it for a ten-minute,
HttpOnly, SameSite-strict browser session; the approval endpoint additionally
requires an explicit confirmation-intent header. A file create with
`overwrite=true` is classified as destructive, never as a remembered reversible
scope. Emergency stop revokes pending/approved grants, clears saved scopes,
cancels queued schedules, terminates active host-agent Docker client processes,
and blocks new host-agent requests. Clearing the stop requires a new local
browser session.

## Isolated self-improvement

Prompts, skills, code, configuration and runbooks are proposed in a dedicated
Git repository under `IMPROVEMENT_WORKSPACE`. Every candidate gets its own
`mica/improvement-*` branch and worktree. Evaluation is sent through the
broker to the separate host agent, which builds and healthchecks
the candidate with no network, a read-only root filesystem, no capabilities,
bounded memory/PIDs and `no-new-privileges`. Only a passing result is fast-forward
promoted after a separate, fresh single-use approval; a bad candidate leaves the
previous active commit untouched, and rollback also needs its own fresh approval.

## Host-agent mTLS boundary

The host agent is deliberately outside this Compose stack: no MICA model or
broker container receives a Docker socket, host mount, or host privilege.
When it is enabled, mount `ca.crt`, `client.crt`, and `client.key` below
`${MICA_DATA_DIR}/host-agent-client`; only `tool-broker` can read that mount.
The separate agent must run on loopback behind the supplied mTLS Caddy example
and have a configured broker certificate subject plus explicit scopes. An
incomplete mTLS configuration fails closed and dispatches nothing.

Host file deletion is implemented as a recoverable move into the configured
host-agent trash and returns an exact undo. Network and administrative changes
can only select operator-owned named argv profiles from the immutable host
configuration; request payloads can never supply shell text or additional
arguments. These operations, Docker lifecycle and isolated self-improvement
also require an approval id again at the host-agent boundary. The emergency
stop marker is durable across host-agent restarts and fails closed if damaged.

Approvals are parameter-bound. Destructive approvals expire and can be used
once; saved reversible approvals apply only to the same canonical parameters.
`POST /v1/emergency-stop` persists a fail-closed stop for new policy decisions
until an authenticated local user clears it.

## Docker failure learning acceptance

Run the controlled acceptance after building the Python image:

```sh
docker build -t mica-core-acceptance -f docker/Dockerfile.python .
docker run --rm -v "$PWD:/workspace:ro" -w /workspace/backend mica-core-acceptance python -m unittest tests.test_docker_learning_acceptance -v
```

The test safely makes the host-agent Docker subprocess return a known
non-zero Docker response. It proves the captured string is retained unchanged
in a Markdown evidence document, a linked Lesson is created, and a repeated
approved call retrieves that Lesson before the host-agent handler. The broker
records the lesson IDs and explicit "no parameter mutation" rule in its audit
authorization; it never silently changes a confirmed Docker operation. This
is a controlled local acceptance, not proof of a live ZimaOS Docker daemon or
the production Caddy mTLS chain.
## API factory

Compose starts the API through `uvicorn backend.services.api.app:create_app --factory`.
Importing the composition module creates no runtime databases. Each factory
call owns its service instances, approval sessions and voice-session registry.
Tests use `create_app(data_dir=temporary_directory)` and may inject dependencies
with `dependencies={"_local_completion": fake_completion}`. The runtime is
available as `app.state.runtime`; the default production paths still come from
the Compose environment. There is no exported process-global `app` instance.
