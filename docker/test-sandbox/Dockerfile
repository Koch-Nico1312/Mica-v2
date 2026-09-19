FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ARG SANDBOX_UID=10001
ARG SANDBOX_GID=10001

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        iproute2 \
        jq \
        openssh-server \
        procps \
    && rm -rf /var/lib/apt/lists/*

# Install the same Python dependencies used by the server-side MICA tests.
COPY mica_core/requirements.txt /tmp/mica-core-requirements.txt
RUN pip install --no-cache-dir -r /tmp/mica-core-requirements.txt \
    && HOME=/opt/mica-build python -c "from tree_sitter_language_pack import download_all; download_all()" \
    && rm -f /tmp/mica-core-requirements.txt

RUN groupadd --gid "${SANDBOX_GID}" codex-test \
    && useradd --uid "${SANDBOX_UID}" --gid "${SANDBOX_GID}" \
        --home-dir /home/codex-test --shell /bin/bash codex-test \
    # Keep the account usable for public-key SSH while password login remains
    # disabled in sshd_config.
    && passwd -d codex-test \
    && install -d -m 0700 -o codex-test -g codex-test /home/codex-test \
    && install -d -m 0750 -o codex-test -g codex-test /work \
    && install -d -m 0700 /etc/ssh/hostkeys

COPY docker/test-sandbox/sshd_config /etc/ssh/sshd_config
COPY docker/test-sandbox/entrypoint.sh /usr/local/sbin/mica-sandbox-entrypoint
RUN chmod 0755 /usr/local/sbin/mica-sandbox-entrypoint \
    && chmod 0600 /etc/ssh/sshd_config

EXPOSE 22
WORKDIR /workspace
ENTRYPOINT ["/usr/local/sbin/mica-sandbox-entrypoint"]
