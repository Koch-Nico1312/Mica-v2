"""Repeatable local benchmarks using disposable data, without external calls."""

from __future__ import annotations

import argparse
import copy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.common.audit import AuditLog
from backend.services.common.brain import MarkdownBrain
from backend.services.common.phase4 import Phase4Store
from desktop.memory import memory_manager


def _elapsed(function, runs: int) -> float:
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        function()
        samples.append(time.perf_counter() - started)
    return round(statistics.median(samples) * 1000, 3)


def benchmark(runs: int = 3) -> dict:
    runs = max(1, min(runs, 30))
    with (
        tempfile.TemporaryDirectory() as directory,
        patch.dict(os.environ, {"MICA_HINDSIGHT_ENABLED": "0"}),
    ):
        root = Path(directory)
        brain = MarkdownBrain(root / "brain", root / "brain.sqlite3")
        for index in range(80):
            metadata = {
                "id": f"{index:032x}",
                "kind": "notes",
                "title": f"Project {index}",
                "created_at": datetime.now(UTC).isoformat(),
            }
            body = (
                "Docker volume diagnosis and local startup verification. " * 20
            ) + f"Probe_{index}"
            (brain.root / f"{index}.md").write_text(
                "---\n" + json.dumps(metadata) + "\n---\n\n" + body, encoding="utf-8"
            )
        brain.reindex()
        result = {
            "brain_80_docs_search_ms": _elapsed(
                lambda: brain.search("Docker", limit=8), runs
            )
        }
        with patch.object(brain, "_chunks", wraps=brain._chunks) as chunks:
            brain.search("Docker")
            result["brain_unchanged_chunker_calls"] = chunks.call_count

        store = Phase4Store(root / "state.sqlite3")
        for index in range(80):
            store.create_plan(
                f"Plan {index}",
                [
                    {
                        "action": "files.list",
                        "params": {},
                        "expected_change": "read source",
                    }
                ],
            )
        with patch.object(store, "_connect", wraps=store._connect) as connection:
            store.list_plans()
            result["list_80_plans_connections"] = connection.call_count
        result["list_80_plans_ms"] = _elapsed(store.list_plans, runs)

        audit = AuditLog(root / "audit.jsonl")
        previous = ""
        with audit.path.open("w", encoding="utf-8", newline="\n") as handle:
            for index in range(6000):
                event = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "type": "benchmark",
                    "payload": {"number": index, "status": "ok"},
                    "previous_hash": previous,
                }
                canonical = json.dumps(
                    event,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                previous = event["hash"] = hashlib.sha256(
                    canonical.encode()
                ).hexdigest()
                handle.write(
                    json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
                )
        tracemalloc.start()
        try:
            audit.read(25)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        result["audit_read_6000_peak_bytes"] = peak
        result["audit_read_6000_ms"] = _elapsed(lambda: audit.read(25), runs)

        memory = {
            "notes": {
                f"entry-{index}": {"value": "x" * 250, "updated": f"{index:04d}"}
                for index in range(1200)
            }
        }
        with patch("builtins.print"):
            result["trim_1200_entries_ms"] = _elapsed(
                lambda: memory_manager._trim_to_limit(copy.deepcopy(memory)), runs
            )
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON result file")
    parser.add_argument(
        "--runs", type=int, default=3, help="Median over this many repetitions (1–30)"
    )
    arguments = parser.parse_args()
    result = json.dumps(benchmark(arguments.runs), indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(result, encoding="utf-8")
    print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
