"""Small, dependency-free liveness markers for non-HTTP worker services.

Compose can probe HTTP services directly.  The indexer and scheduler are
long-running workers, so their health checks use an atomically updated marker
instead of treating a live-but-stuck PID as healthy.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def marker_path(name: str) -> Path:
    root = Path(os.getenv("MICA_HEALTH_DIR", "/data/health"))
    return root / f"{name}.json"


def touch(name: str) -> None:
    """Publish a marker only after one complete worker iteration."""
    target = marker_path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(json.dumps({"updated_at": time.time()}), encoding="utf-8")
    os.replace(temporary, target)


def reset(name: str) -> None:
    """Discard a previous container's marker before the new worker is ready."""
    marker_path(name).unlink(missing_ok=True)


def fresh(name: str, max_age_seconds: float) -> bool:
    """Return true only for a parseable marker from a recent iteration."""
    try:
        payload = json.loads(marker_path(name).read_text(encoding="utf-8"))
        updated_at = float(payload["updated_at"])
        return 0 <= time.time() - updated_at <= max_age_seconds
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
