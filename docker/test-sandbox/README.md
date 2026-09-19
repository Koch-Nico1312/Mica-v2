# Isolated SSH test sandbox

This Compose project gives an SSH client access to an unprivileged shell inside
one disposable test container. It does not mount the host Docker socket, devices,
host root, user homes, application data or secrets. The repository is mounted
read-only; `/work` is the only persistent writable volume. Runtime networking
is internal, so the test container has no default Internet route. A separate,
capability-free `socat` gateway owns the published port and forwards only the
SSH byte stream; it receives no repository, key, writable state or shell.

This is suitable for source inspection and the Python acceptance tests. It is
deliberately unable to create, stop or inspect sibling host containers. Full
MICA Compose and GPU-passthrough acceptance belongs inside a disposable VM;
mounting `/var/run/docker.sock` here would defeat the isolation boundary.

## 1. Generate the client key on the laptop

The private key must stay on the client. In PowerShell:

```powershell
ssh-keygen -t ed25519 -a 100 -f "$env:USERPROFILE\.ssh\mica-test-sandbox" -C "mica-test-sandbox"
```

Use a passphrase. The public half is
`$env:USERPROFILE\.ssh\mica-test-sandbox.pub`.

## 2. Install only the public key on the server

Create `.sandbox/authorized_keys` beside the Compose file and copy the single
public-key line into it. Prefixing it with `restrict,pty ` adds a second SSH
restriction layer while preserving an interactive terminal:

```text
restrict,pty ssh-ed25519 AAAA... mica-test-sandbox
```

Never copy `mica-test-sandbox` without the `.pub` suffix to the server.

## 3. Configure and start

Copy `.env.test-sandbox.example` to `.env.test-sandbox`. Keep the bind address
on loopback for a VPN/tunnel, or set it to the server's exact LAN address and
allow the chosen port only from the laptop in the server firewall.

```powershell
docker compose --env-file .env.test-sandbox -f docker-compose.test-sandbox.yml up -d --build
```

Check that the service reports `healthy` before connecting.

## 4. Connect

```powershell
ssh -i "$env:USERPROFILE\.ssh\mica-test-sandbox" -p 2222 codex-test@SERVER_ADDRESS
```

Inside the container, `/workspace` is read-only and `/work` is writable. A
useful first verification is `id`; it must report uid and gid `10001`, not root.

## Revocation and cleanup

Removing the public-key line immediately revokes future logins. `docker compose
down` removes the container and network while preserving `/work` and the SSH
host identity. `docker compose down -v` additionally erases both sandbox
volumes; use that only when their contents are no longer needed.

Containers share the host kernel. This setup substantially limits authority,
but a disposable Proxmox VM remains the stronger boundary for untrusted code,
GPU passthrough or full Docker-stack control.

The two official base images are pinned by digest to the versions exercised by
the smoke test. Refresh those digests deliberately when applying base-image
security updates, then rebuild and repeat the SSH/isolation tests.
