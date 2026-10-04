# MICA Windows Host Agent

This process is the Phase-0 security boundary for native Windows actions. Run
the FastAPI application only on `127.0.0.1:8766`; expose it solely through the
provided Caddy mTLS configuration, which also binds only to `127.0.0.1:9443`.
Caddy replaces any inbound identity headers with values derived after verified
client authentication. From an elevated PowerShell, run
`Install-FirewallRule.ps1`; its TCP and UDP block rules are defence in depth
against an accidental future LAN bind.

Run `New-MicaMtlsCertificates.ps1` once from an elevated PowerShell. It creates
the server certificate for `host.docker.internal`, the broker client identity
`CN=mica-tool-broker`, and restrictive Windows ACLs. It refuses to overwrite
existing material. Keep `broker-ca.key` offline after setup; only
`broker-ca.crt`, `client.crt` and `client.key` belong in the broker's read-only
`host-agent-client` mount.

With the loopback agent and Caddy running, record both the successful client
identity and rejection without a client certificate:

`python backend\windows_host_agent\mtls_probe.py --connect-host 127.0.0.1 --host host.docker.internal --ca C:\ProgramData\Mica\tls\broker-ca.crt --cert C:\ProgramData\Mica\tls\client.crt --key C:\ProgramData\Mica\tls\client.key --output .mica-data\workspace\artifacts\phase0-mtls-current.json`

`--connect-host` addresses Caddy's loopback-only listener. Certificate and HTTP
host verification deliberately continue to use `host.docker.internal`.

Copy `config.example.json` to `%ProgramData%\Mica\windows-host-agent.json` and
remove every action that has not been explicitly approved. Set
`MICA_WINDOWS_ENABLED_ACTIONS` to the same comma-separated list. Networked
capabilities additionally require their individual
`MICA_CAPABILITY_<MODULE>_NETWORK=true` opt-in, an exact hostname list in
`MICA_CAPABILITY_<MODULE>_TARGETS`, and any declared secret. Messaging also
requires exact recipients in `MICA_CAPABILITY_SEND_MESSAGE_RECIPIENTS`.
File-bearing parameters fail closed unless their resolved path is inside one
of the semicolon-separated roots in `MICA_WINDOWS_ALLOWED_ROOTS`.
Application launches are separately denied unless the exact requested alias is
listed in the comma-separated `MICA_WINDOWS_ALLOWED_APPS` variable (for
example `notepad,calculator`).

Each request has a short expiry and a UUID that is permanently claimed in a
local SQLite replay database. Non-read actions require an approval id. Every
action runs in a fresh child process with no shell and a fixed adapter mapping.
Cloud-model-dependent legacy branches fail closed until their local adapter is
implemented.

The Phase-0 replacements expose only bounded local operations for the former
cloud-only modules: `dev_agent.inspect` returns project metadata without file
contents or changes, and `screen_process.capture_metadata` returns dimensions
and an in-memory pixel hash without persisting the capture. Autonomous project
generation/repair and visual interpretation remain unavailable until they have
local-model adapters and their own acceptance evidence.

The emergency stop survives restarts and terminates active child processes.
Remote resume is disabled by default. After checking logs, pending approvals,
scheduled actions and host state, a local administrator may temporarily set
`allow_broker_resume` to `true`, clear the stop through the authenticated API,
then set it back to `false`.

Development start command (loopback only):

`$env:PYTHONPATH="$PWD\backend;$PWD\desktop;$PWD"; python -m uvicorn backend.windows_host_agent.app:app --host 127.0.0.1 --port 8766`
