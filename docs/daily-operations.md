# MICA im Alltag

Implementation, 2026-10-01. The desktop uses the existing local backend and
parameter-bound authorization for all five areas.

## Desktop navigation

`Betrieb` opens backend tasks, agent plans, execution status, service diagnostics
and a combined desktop/backend action view. Network calls run on workers and
results return through Qt signals. The existing Chat, Verlauf, Erinnerungen,
Gedächtnis and Einstellungen destinations retain their indexes.

The local launcher replaces the legacy desktop-only memory page with the actual
backend Markdown documents. Entries show their source and timestamp. Explicit
remember, correction and deletion require a ten-minute local approval session;
the password is not saved. The no-storage checkbox covers subsequent text turns
and voice sessions. It suppresses conversation documents and digital-twin
observations. It does not disable cloud providers already selected by the user,
nor does it erase existing memories. Content-free operational audit remains.

### Task overview, 2026-10-04

The tasks tab provides text search and filters for attention, running and
finished items. Plans show completed/total steps; the table distinguishes task
items, agent plans and individual executions. Timestamps use Europe/Vienna.
Selection survives refresh by the item identity, rather than its row position.
Filtering a selected item out clears the selection and its action controls.

Controls are offered according to the selected item's lifecycle. They include
plan preview, pause, continuation and cancellation; outcome reconciliation;
known-undispatched execution continuation; and marking ordinary task items as
in progress or completed. Task-item status changes do not execute host actions.
Cancellation requires confirmation and does not undo completed changes or
guarantee interruption of an already dispatched action. Existing backend
feature gates, exact approvals and execution identities remain authoritative.

Paused plans with unresolved dispatched steps cannot be resumed from this view.
Cancelled plans with unresolved effects remain in the attention filter and
link to the action history rather than offering reactivation.
Uncertain executions never offer replay, even if a contradictory retry flag
is supplied. Failed refreshes retain the visible snapshot but mark it stale
and disable changes until a successful refresh. Reconciliation reports whether
an outcome was actually confirmed and refreshes the task snapshot; a successful
HTTP request alone is not displayed as a confirmed action result.

### Memory overview, 2026-10-04

The backend memory page offers text search and classification filters. Entries
show document type, source, creation and update dates in Europe/Vienna.
Classification uses explicit metadata: inferred entries and reflections are
shown as assumptions, explicitly remembered entries as user-saved information,
and entries without confirmation metadata as unconfirmed. Source names alone
do not establish confirmation. These labels do not independently verify facts
and do not promote assumptions into confirmed memory.

The editor remains bound to the document identity when filtering or refreshing.
Switching entries or starting a new one asks before discarding an unsaved draft.
A failed refresh retains drafts and disables writes until reloading succeeds.
Changes or deletions detected during refresh block writes to that draft until
the saved version is explicitly reloaded. This is refresh-time conflict detection,
not an atomic backend version check. Existing titles are read-only because the
correction endpoint updates document content, not its title. Local editing
authorization expires after ten minutes without deleting the draft; backend
authorization remains authoritative. Optional Hindsight behavior is unchanged.

### Response timings, 2026-10-04

`Betrieb` -> `Diagnose` shows the most recent 100 completed text/voice timings
for the current desktop process. The table refreshes locally, without sending
additional requests. Timings contain only type, outcome, timestamp and durations;
no prompts, transcripts, responses, audio, URLs, credentials or error messages
are retained. They are not written to disk or sent to the backend. The delete
control clears completed measurements; running requests may finish afterwards.
No-storage mode still permits these content-free measurements.

Text response time starts immediately before the synchronous Core turn request
and ends after the full JSON response has been received and validated. It is
not streaming first-token latency and excludes time waiting for the desktop
request lock and subsequent UI rendering. Voice transcript, text and audio
durations start before sending `finalize`, after queued audio has been sent.
Audio timing means complete WAV receipt, not audible playback onset. Voice
total duration starts when capture is requested and includes setup, recording
and playback up to completion, failure or cancellation detection, excluding
subsequent cleanup. Connection timing is available in row tooltips.

Text and voice medians are separate and use successful reply timings only;
failures and cancellations remain visible but are not counted as successful
responses. Monotonic clocks avoid wall-clock adjustment errors. These are
observed client durations, not isolated backend/model processing measurements
or a physical microphone/speaker performance acceptance result.

## Execution and recovery boundary

API executions use a durable journal in the scheduler database. The default
idempotency key derives from the supplied task ID; callers must retain that ID
when retrying. Concurrent matching requests dispatch once. Completed successful
results are returned from the journal. Changed task IDs or parameters under an
existing key are rejected. Explicit preflight or approval denials permit a retry
with the same identity. Timeouts, unexpected failures and process interruptions
retain their dispatch claim; the API cannot infer that an external effect did
not happen. Dry runs do not claim execution keys.
The journal retains exact action parameters for targeted continuation; it never
stores approval tokens. No-storage conversation mode does not dispatch actions.

Explicitly paused intervals do not consume an agent plan's active time budget.
Resuming retains consumed active time and all tool-call/correction counters.

The desktop can pause active agent plans, compare uncertain outcomes against
the broker's durable results, and activate ready/paused plans through the
existing policy endpoint. Only a matching parameter fingerprint and confirmed
dispatch can mark an interrupted step complete. Remaining steps can then run;
the completed step is not redispatched. Unknown results remain blocked. The
Freigaben tab supports login, inspecting exact pending parameters, confirmation,
plan resumption and clearing emergency stop after review. Feature gates still
apply. A process-shared dispatcher lock prevents a second live scheduler from
misidentifying a running step as a crashed one.

## Diagnostics and action history

Diagnostics probe configured local LLM, STT, TTS and broker `/health` endpoints,
with strict local-host validation, no redirects and bounded timeouts. They also
show Phase-0 checks and blocked capabilities. Repair controls invoke the local
credential-aware Compose launcher, set an allowlisted local HTTPS endpoint and
CA certificate, or open provider/model settings. They are followed by explicit
health verification; successful `up -d` alone does not prove readiness.

Desktop undo registrations are logged durably under `.mica-data`. Available undo
closures belong to the running session; after restart their descriptions remain
but the interface does not promise an executable undo. Undo confirmation binds
to the exact latest entry so a newer action cannot accidentally be reversed.
Backend executions share the action view but their host undo integration remains
to be completed. Actions without an undo registration need comprehensive logging.

## Backup and restore

The Backup tab exports a ZIP containing validated backend truth and allowlisted
desktop state/settings. Provider secrets and raw `.env` files are excluded. A
backend restore validates archive hashes and reconstructed logical state before
touching live data. Linux/Windows process-shared reader/writer locks drain API,
broker, voice-turn, scheduler, indexer and Hindsight-sync operations. Incomplete
restores leave a marker that blocks writers, with an authenticated recovery
download and retry path. Before changes, both backend and desktop retain recovery
copies. Desktop writes roll back on an exception. The live audit and broker
idempotency state are preserved. Existing execution/plan claims and delivery
outcomes remain sticky to prevent an old snapshot causing duplicate effects.
Restored plans are paused, automation rules disabled and emergency stop active.
Desktop settings take effect after restart. Backups do not contain OS credentials,
model binaries or the separate optional Hindsight server database. The API
requires the documented common backend data layout. Configurations whose truth
is spread across other directories are explicitly rejected by these UI routes.

The no-storage preference now survives desktop restart and is included in the
settings backup. Research entries expose source URLs alongside source kind.

### Update safety and backup inspection, 2026-10-04

The Backup tab can inspect a ZIP or backend TAR.GZ without applying it. The
inspection verifies hashes, audit integrity and the rebuilt logical backend
state in a disposable directory. Restoration performs this inspection before
calling the live backend restore route. The backend still independently
validates the uploaded archive. A partial desktop failure is reported separately
from a completed backend restore; it is not reported as full success.

`Update-Sicherung erstellen` requires an unchanged Git checkout and an unlocked
backend backup session. It saves a verified data ZIP and a Git bundle of HEAD
with its reachable committed history under `.mica-data/update-recovery/<id>/`.
The checkpoint manifest binds hashes and the exact source commit. Publication
happens only after verification and a second unchanged-project check; failures
leave source unchanged and do not publish a checkpoint. Backups contain private
data and are not encrypted. Source bundles contain tracked history, including
whatever was committed there, not uncommitted edits.

The installation launcher requires a valid checkpoint for the current HEAD,
not older than 24 hours, before an automatic fast-forward. It verifies the
checkpoint again, rechecks the project and merges exactly the fetched commit
without a second fetch. Missing, damaged, expired checkpoints and dirty or
diverged checkouts skip source updates while allowing the installed app to
start. No source update has been performed merely by creating a checkpoint.
The ordinary `Start MICA.cmd` path does not apply source updates.

The data ZIP can be restored through the existing Backup tab. The source bundle
is available for deliberate source recovery into a separate checkout; there
is no destructive automatic code rollback. Dependencies/virtual environments,
model binaries, Windows Credential Manager entries, external Hindsight data and
host OS changes are outside this recovery point. Running applications and
backend deployments are not replaced by this desktop source-update guard.
Data changes made after the snapshot are not included, even within its 24-hour
validity window. Keep checkpoint directories private and retain them until the
new installation has been checked; old snapshots are not automatically deleted.

## Action history and undo

Every Windows runner action has a durable host receipt. The UI combines these
with API executions, plan steps (including server actions), and legacy desktop
undo registrations. A host receipt exposes action, operation, affected paths,
status and actual undo availability. Typed compensation survives subprocess and
host restarts for small file create/write/copy/move/rename operations and empty
folder creation. Previous bytes are kept only on the host, up to 1 MB per file.
Undo rechecks the current allowlisted roots, rejects links/junctions and refuses
files changed since the original action. Unsupported operations, nonempty
directory trees, large files and overwritten move destinations have no
advertised automatic undo. Undo is a parameter-bound, single-use approved action
through the existing broker, with a stable execution key. Interrupted undo stays
uncertain and is never automatically replayed. The runner uses UTF-8 explicitly.

Known undispatched API executions can resume from the tasks page after restart,
using their saved parameters, task ID and execution key. Unknown outcomes remain
blocked. New approvals are confirmed in the Freigaben tab before continuing.

Verification of the actual target deployment remains separate from isolated
runtime acceptance. No existing host configuration was activated.

Focused tests in `tests/test_daily_operations.py` exercise journal restart,
parallel claims, cached API results, timeout protection, denied edits, memory
correction/deletion, private text, local-only probes, UI rendering and stale undo.
The tests also run a real Uvicorn HTTPS server with a temporary trusted CA and
exercise the production LocalCoreClient login, memory edits, archive streaming,
restore and recovery download. This proves local transport/runtime behavior,
not a deployed Docker stack, live model quality or physical microphone behavior.

Latest validation: the complete `tests/` run passed 508 tests and 70 subtests,
with two dependency deprecation warnings. The final migration fix and its new
test passed four focused legacy regressions; independent final review passed
12 selected tests and found no further actionable bugs. See
[bugfix review](01.10.26-bugbot-corrections.md) for findings and validation scope.
The earlier focused HUD run passed 13 tests, including the wide operations view
and restoration of the chat context panel.
Visual checks used the actual Qt shell at 1100 by 740 pixels. Git whitespace
checks passed. The host compensation tests use real separate runner processes;
the voice test verifies forwarding the no-storage flag through the WebSocket.
