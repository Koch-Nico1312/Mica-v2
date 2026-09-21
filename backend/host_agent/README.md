# MICA Host Agent Protocol

The host agent is deployed separately on Windows, Linux, or ZimaOS. Start
`app.py` only on loopback, then place the included Caddy configuration in front
of it with a broker CA and host certificate. Its request id table rejects a
replay; it accepts only the certificate subject and allowlisted scopes in
`config.json`. Shell text, Docker socket requests, arbitrary path traversal and
unimplemented scopes are rejected.

Copy `config.example.json` to the deployed volume and set the local data root.
The agent implements bounded `system.status`, `files.list`, `files.create`,
`files.move`, recoverable `files.delete`, `docker.status`, allowlisted
`docker.lifecycle`, and operator-defined `network.change`/`system.admin`
actions. A delete moves one regular file below the configured `trash_root` and
returns an exact `files.move` undo; it never recursively removes a directory.
Network profiles and administration actions are fixed argv arrays in the local
host configuration. The request selects only a profile/state or action name;
it cannot add a command, argument, pipe or shell expression. Docker operations
likewise use a fixed argv and an exact `allowed_containers` list. Leave
`network_profiles` and `admin_actions` empty until an administrator has reviewed
each platform-specific command. Host secrets and the policy engine never leave
their respective hosts. See `../services/common/policy.py` for the matching
risk boundaries.

The host boundary independently requires a parameter-bound approval id for
file deletion, network changes, Docker lifecycle, system administration and
self-improvement, even if a broker regression were to send a destructive call
without one. Emergency stop is persisted in `MICA_HOST_AGENT_STOP_STATE`; a
restart remains stopped, and a damaged marker fails closed until an
authenticated local operator explicitly clears it.

`Dockerfile` is provided for the separately deployed agent. Only this isolated
agent may receive the Docker socket and the configured improvement worktree;
the MICA Compose stack never does. The `improvement.shadow` handler builds a
candidate Git branch with `--network=none`, runs its healthcheck read-only with
all capabilities dropped, and leaves the active revision untouched on failure.
For promoted `code` skills, `improvement.invoke` accepts only the exact revision
listed in the atomically published runtime manifest and the still-labelled
shadow image. It runs that image without network, with a read-only filesystem,
no capabilities, bounded memory/processes, a short host timeout and JSON-only
input/output. Every invocation requires a fresh parameter-bound browser
approval; code is never imported into the API, broker or policy process.
