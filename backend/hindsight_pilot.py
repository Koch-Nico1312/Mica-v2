"""Real-server acceptance and retrieval comparison using isolated test sources."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
from contextlib import nullcontext
import time
import uuid

from backend.services.common.brain import MarkdownBrain
from backend.services.common.hindsight import HindsightMemory


def run(url: str, report_path: Path, container: str | None = None) -> dict:
    original = dict(os.environ)
    report = {"schema": 1, "started_at": datetime.now(UTC).isoformat(), "passed": False,
              "source": "isolated representative MICA test excerpts", "live_server_requested": True, "checks": {}, "comparison": []}
    try:
        with nullcontext(report_path.parent / f"state-{uuid.uuid4().hex[:12]}") as temporary:
            root = Path(temporary)
            os.environ.update({"MICA_HINDSIGHT_ENABLED": "1", "MICA_HINDSIGHT_ALLOW_PRIVATE": "1",
                               "MICA_HINDSIGHT_URL": url, "MICA_HINDSIGHT_BANK": f"mica-pilot-{uuid.uuid4().hex[:12]}",
                               "MICA_HINDSIGHT_DB": str(root / "sync.sqlite3"), "MICA_HINDSIGHT_ALLOW_REMOTE": "0",
                               "MICA_HINDSIGHT_REFLECT_TIMEOUT": "180"})
            report["bank"] = os.environ["MICA_HINDSIGHT_BANK"]
            report["state_directory"] = str(root)
            os.environ.pop("MICA_HINDSIGHT_API_KEY", None)
            brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
            memory = HindsightMemory(brain)
            cases = [
                ("Stimme", "Der Nutzer wünscht eine weibliche Stimme unabhängig vom API-Anbieter.", "Welche Sprachausgabe bevorzugt der Nutzer?"),
                ("Docker-Reparatur", "Docker startete nicht wegen einer veralteten engine.sock. Das temporäre Socket-Verzeichnis wurde gesichert und Docker neu gestartet; Images und Volumes blieben erhalten.", "Wie wurde das Problem beim Start des Containerdienstes gelöst?"),
                ("Projektentscheidung", "Für MICA bleiben Markdown-Dateien die maßgebliche Wissensquelle. Hindsight ist eine optionale Ergänzung.", "Welcher Speicher ist für die Assistenz verbindlich?"),
            ]
            sources = [brain.write("memory", title, text) for title, text, _ in cases]
            started = time.perf_counter()
            result = memory.sync(limit=10)
            report["retain_seconds"] = round(time.perf_counter() - started, 3)
            report["checks"]["retain"] = result["status"] == "ready"
            if not report["checks"]["retain"]:
                raise RuntimeError(f"retain {result['status']}")
            report["checks"]["restart_idempotent"] = HindsightMemory(brain).sync()["processed"] == 0
            for source, (_, _, query) in zip(sources, cases):
                os.environ["MICA_HINDSIGHT_ENABLED"] = "0"
                started = time.perf_counter()
                local = brain.search(query, limit=3)
                local_seconds = time.perf_counter() - started
                os.environ["MICA_HINDSIGHT_ENABLED"] = "1"
                started = time.perf_counter()
                remote = memory.recall(query, limit=3)
                remote_seconds = time.perf_counter() - started
                started = time.perf_counter()
                hybrid = brain.search(query, limit=3)
                hybrid_seconds = time.perf_counter() - started
                report["comparison"].append({"query": query, "expected_source": source["id"],
                    "local_rank": next((i + 1 for i, item in enumerate(local) if item["id"] == source["id"]), None),
                    "hindsight_rank": next((i + 1 for i, item in enumerate(remote) if item["id"] == source["id"]), None),
                    "hybrid_rank": next((i + 1 for i, item in enumerate(hybrid) if item["id"] == source["id"]), None),
                    "local_seconds": round(local_seconds, 3), "hindsight_seconds": round(remote_seconds, 3),
                    "hybrid_seconds": round(hybrid_seconds, 3)})
            report["checks"]["recall"] = all(item["hindsight_rank"] is not None for item in report["comparison"])
            if container:
                labels = json.loads(subprocess.check_output(
                    ["docker", "inspect", container, "--format", "{{json .Config.Labels}}"], text=True,
                ))
                if labels.get("com.docker.compose.project") != "mica-hindsight-pilot":
                    raise ValueError("Only the isolated pilot container may be restarted")
                subprocess.run(["docker", "stop", container], check=True, capture_output=True)
                try:
                    started = time.perf_counter()
                    fallback = brain.search("weibliche Stimme", limit=3)
                    report["outage_fallback_seconds"] = round(time.perf_counter() - started, 3)
                    report["checks"]["outage_fallback"] = bool(fallback) and not any(item.get("retrieval") == "hindsight" for item in fallback)
                finally:
                    subprocess.run(["docker", "start", container], check=True, capture_output=True)
                deadline = time.monotonic() + 180
                import httpx
                while time.monotonic() < deadline:
                    try:
                        response = httpx.get(f"{url}/health", timeout=2, trust_env=False)
                        if response.status_code == 200 and response.json().get("status") == "healthy":
                            break
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(2)
                else:
                    raise RuntimeError("Pilot server did not recover after restart")
                report["checks"]["server_restart"] = bool(memory.recall(cases[0][2]))
            started = time.perf_counter()
            reflection = memory.reflect("Welche Speicherentscheidung und welche Sprachpräferenz gelten für MICA?")
            report["reflect_seconds"] = round(time.perf_counter() - started, 3)
            report["reflection"] = reflection
            report["checks"]["reflect"] = reflection["status"] == "ready"
            text = reflection.get("text", "").lower()
            report["checks"]["reflect_content"] = "markdown" in text and any(word in text for word in ("weiblich", "female"))
            source = sources[0]
            brain.update_document(source["id"], "Der Nutzer wünscht weiterhin eine weibliche Stimme, jetzt lokal mit Kerstin.")
            report["checks"]["stale_source_rejected"] = all(item["id"] != source["id"] for item in memory.recall("Stimme"))
            report["checks"]["correction"] = memory.sync()["status"] == "ready"
            for source in sources:
                brain.delete_document(source["id"])
            report["checks"]["deletion"] = memory.sync(limit=10)["status"] == "ready"
            raw = memory._request("POST", "memories/recall", {"query": "MICA Stimme Docker", "max_tokens": 1000})
            report["checks"]["remote_empty"] = not raw.get("results")
            report["passed"] = all(report["checks"].values())
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        os.environ.clear()
        os.environ.update(original)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8889")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--restart-container", help="Exercise outage/restart of a container belonging to mica-hindsight-pilot")
    args = parser.parse_args()
    result = run(args.url, args.report, args.restart_container)
    print(json.dumps({"passed": result["passed"], "checks": result["checks"], "error": result.get("error"), "report": str(args.report)}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
