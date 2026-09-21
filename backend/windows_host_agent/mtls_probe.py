"""Repeatable positive/negative mTLS probe for the Windows host boundary."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import socket
import ssl


def _http_request(connect_host: str, server_name: str, port: int, context: ssl.SSLContext) -> bytes:
    with socket.create_connection((connect_host, port), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=server_name) as secured:
            secured.sendall(
                f"GET /health HTTP/1.1\r\nHost: {server_name}\r\nConnection: close\r\n\r\n".encode("ascii")
            )
            chunks: list[bytes] = []
            while True:
                chunk = secured.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)


def probe(
    host: str,
    port: int,
    ca: Path,
    certificate: Path,
    key: Path,
    *,
    connect_host: str | None = None,
) -> dict[str, object]:
    target = connect_host or host
    authenticated_context = ssl.create_default_context(cafile=str(ca))
    authenticated_context.load_cert_chain(str(certificate), str(key))
    authenticated = _http_request(target, host, port, authenticated_context)
    positive_ok = authenticated.startswith(b"HTTP/1.1 200") and b'"authority":"allowlisted-mtls-subprocess-only"' in authenticated

    unauthenticated_context = ssl.create_default_context(cafile=str(ca))
    negative_ok = False
    negative_reason = "connection_unexpectedly_succeeded"
    try:
        _http_request(target, host, port, unauthenticated_context)
    except (ssl.SSLError, ConnectionError, OSError) as error:
        negative_ok = True
        negative_reason = type(error).__name__

    return {
        "schema_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "host": host,
        "connect_host": target,
        "port": port,
        "authenticated_health_ok": positive_ok,
        "unauthenticated_rejected": negative_ok,
        "unauthenticated_result": negative_reason,
        "ready": positive_ok and negative_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="host.docker.internal")
    parser.add_argument(
        "--connect-host", default="127.0.0.1",
        help="TCP destination; TLS and HTTP still verify/use --host",
    )
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--ca", required=True, type=Path)
    parser.add_argument("--cert", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = probe(
        arguments.host, arguments.port, arguments.ca, arguments.cert, arguments.key,
        connect_host=arguments.connect_host,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output:
        destination = arguments.output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(destination)
    print(encoded)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
