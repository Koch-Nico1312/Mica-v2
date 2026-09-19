#!/bin/sh
set -eu

authorized_keys=/run/secrets/sandbox_authorized_keys
host_key=/etc/ssh/hostkeys/ssh_host_ed25519_key

if [ ! -s "$authorized_keys" ]; then
    echo "Refusing to start: the authorized_keys secret is missing or empty." >&2
    exit 64
fi

if grep -q "PRIVATE KEY" "$authorized_keys"; then
    echo "Refusing to start: mount only a public key, never a private key." >&2
    exit 65
fi

if ! grep -Eq '(^|[[:space:]])(ssh-ed25519|sk-ssh-ed25519@openssh.com)[[:space:]]' "$authorized_keys"; then
    echo "Refusing to start: no supported Ed25519 public key was found." >&2
    exit 66
fi

install -d -m 0755 /run/sshd
# Compose secrets are read-only, but Docker Desktop may expose host-specific
# mode bits. Copy the public material into the root-owned tmpfs before sshd's
# StrictModes check; the unprivileged login user cannot alter this copy.
cp "$authorized_keys" /run/sshd/authorized_keys
chown 0:0 /run/sshd/authorized_keys
chmod 0644 /run/sshd/authorized_keys
# Named volumes survive container recreation and may already belong to uid
# 10001. Temporarily take ownership so chmod does not require CAP_FOWNER.
chown 0:0 /work /home/codex-test
chmod 0750 /work
chmod 0700 /home/codex-test
chown 10001:10001 /work /home/codex-test

if [ ! -s "$host_key" ]; then
    ssh-keygen -q -t ed25519 -N '' -f "$host_key"
fi
chmod 0600 "$host_key"
chmod 0644 "${host_key}.pub"

/usr/sbin/sshd -t -f /etc/ssh/sshd_config
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config
