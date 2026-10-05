"""Copied into a networkless shadow image; never executes in the API process."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import subprocess
import sys
import time


CHILD = """
import json,sys
data=json.loads(sys.stdin.read())
safe={k:getattr(__import__('builtins'),k) for k in
('abs','all','any','bool','dict','enumerate','float','int','len','list','max','min','range','round','sorted','str','sum','tuple','zip')}
scope={'__builtins__':safe}
exec(compile(data['source'],'candidate','exec'),scope,scope)
print(json.dumps(scope['main'](data['input']),ensure_ascii=False,allow_nan=False))
"""


def evaluate(source: str, cases: list[dict]) -> dict:
    results = []
    durations = []
    for case in cases:
        timings = []
        correct = True
        error = None
        for _ in range(2):
            start = time.perf_counter()
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-c", CHILD],
                    input=json.dumps({"source": source, "input": case["input"]}),
                    capture_output=True, text=True, timeout=0.75,
                )
                value = json.loads(proc.stdout) if proc.returncode == 0 else None
                # Canonical JSON equality distinguishes false/0 and null/errors.
                correct = correct and proc.returncode == 0 and (
                    json.dumps(value, sort_keys=True, allow_nan=False) == json.dumps(case["expected"], sort_keys=True, allow_nan=False)
                )
                if proc.returncode != 0:
                    error = "execution_failed"
            except subprocess.TimeoutExpired:
                correct, error = False, "timeout"
            except (ValueError, TypeError):
                correct, error = False, "invalid_output"
            timings.append((time.perf_counter() - start) * 1000)
        duration = statistics.median(timings)
        durations.append(duration)
        results.append({"case_id": case["id"], "correct": correct, "error": error, "duration_ms": round(duration, 3)})
    return {
        "cases": results, "correct": sum(row["correct"] for row in results),
        "errors": sum(row["error"] is not None for row in results),
        "duration_ms": round(sum(durations), 3), "provider_cost": 0.0,
        "user_corrections": None, "measurement": "isolated_fixture_run",
    }


def compare(bundle: dict) -> dict:
    baseline = evaluate(bundle["baseline"], bundle["cases"])
    candidate = evaluate(bundle["candidate"], bundle["cases"])
    regressions = [old["case_id"] for old, new in zip(baseline["cases"], candidate["cases"]) if old["correct"] and not new["correct"]]
    reproduced = baseline["correct"] < len(bundle["cases"])
    # Correctness is the gate. Timing is evidence, never a substitute for output.
    passed = candidate["correct"] == len(bundle["cases"]) and not regressions
    if bundle.get("intent") == "repair":
        passed = passed and reproduced and candidate["correct"] > baseline["correct"]
    return {"baseline": baseline, "candidate": candidate, "regressions": regressions,
            "reproduced": reproduced, "passed": passed, "suite_id": bundle["suite_id"]}


if __name__ == "__main__":
    bundle = json.loads(Path("/shadow/quality.json").read_text(encoding="utf-8"))
    print(json.dumps(compare(bundle), ensure_ascii=False, allow_nan=False))
