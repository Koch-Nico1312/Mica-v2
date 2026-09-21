"""Offline physical acceptance for an operator-provided Hey-Mica ONNX model.

This intentionally bypasses the production provenance gate only inside this
manual acceptance tool. PCM blocks are evaluated in memory and discarded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_OUTPUT = Path(".mica-data/workspace/artifacts/phase0-wake-word-acceptance-current.json")


def _read(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, section: str, value: dict[str, object]) -> dict[str, object]:
    result = _read(path)
    result.update({"schema_version": 1, section: value})
    detections = result.get("detections", {})
    background = result.get("background", {})
    result["summary"] = {
        "detections_passed": bool(isinstance(detections, dict) and detections.get("passed")),
        "background_passed": bool(isinstance(background, dict) and background.get("passed")),
        "passed": bool(
            isinstance(detections, dict) and detections.get("passed")
            and isinstance(background, dict) and background.get("passed")
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return result


def _model(path: Path, vad_threshold: float):
    from openwakeword.model import Model  # type: ignore[import-not-found]

    return Model(wakeword_models=[str(path)], vad_threshold=vad_threshold)


def _window(model, duration: float, device: int | str | None) -> float:
    import numpy as np  # type: ignore[import-not-found]
    import sounddevice as sd  # type: ignore[import-not-found]

    maximum = 0.0
    blocks = max(1, int(duration * 16000 / 1280))
    with sd.RawInputStream(
        samplerate=16000, channels=1, dtype="int16", blocksize=1280, device=device,
    ) as stream:
        for _ in range(blocks):
            raw, _overflowed = stream.read(1280)
            prediction = model.predict(np.frombuffer(bytes(raw), dtype=np.int16))
            maximum = max(maximum, max((float(value) for value in prediction.values()), default=0.0))
    return maximum


def run_detections(args) -> int:
    model = _model(args.model, args.vad_threshold)
    trials: list[dict[str, object]] = []
    print("40 echte Versuche. Sage nach jedem Enter deutlich 'Hey Mica'. Audio wird nicht gespeichert.")
    for number in range(1, 41):
        input(f"{number}/40 – Enter, dann innerhalb von {args.window:.1f}s 'Hey Mica' sagen …")
        score = _window(model, args.window, args.device)
        detected = score >= args.threshold
        trials.append({"trial": number, "max_score": round(score, 6), "detected": detected})
        print(f"Score {score:.3f} – {'Treffer' if detected else 'kein Treffer'}")
    count = sum(bool(item["detected"]) for item in trials)
    section = {
        "checked_at": datetime.now(UTC).isoformat(), "model": str(args.model),
        "sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
        "source": args.source, "version": args.version, "license": args.license,
        "device": args.device, "threshold": args.threshold, "vad_threshold": args.vad_threshold,
        "utterances": 40, "detections": count, "required_detections": 38,
        "trials": trials, "passed": count >= 38, "audio_saved": False,
    }
    result = _write(args.output, "detections", section)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if section["passed"] else 2


def run_background(args) -> int:
    import numpy as np  # type: ignore[import-not-found]
    import sounddevice as sd  # type: ignore[import-not-found]

    model = _model(args.model, args.vad_threshold)
    requested = max(1.0, args.hours * 3600)
    started_wall = datetime.now(UTC)
    started = time.monotonic()
    last_trigger = -args.cooldown
    triggers: list[dict[str, object]] = []
    interrupted = False
    print(f"Hintergrundtest läuft {args.hours:g} Stunden. Audio wird blockweise verworfen. Strg+C beendet unvollständig.")
    try:
        with sd.RawInputStream(
            samplerate=16000, channels=1, dtype="int16", blocksize=1280, device=args.device,
        ) as stream:
            while time.monotonic() - started < requested:
                raw, _overflowed = stream.read(1280)
                prediction = model.predict(np.frombuffer(bytes(raw), dtype=np.int16))
                score = max((float(value) for value in prediction.values()), default=0.0)
                elapsed = time.monotonic() - started
                if score >= args.threshold and elapsed - last_trigger >= args.cooldown:
                    last_trigger = elapsed
                    triggers.append({"elapsed_seconds": round(elapsed, 3), "score": round(score, 6)})
    except KeyboardInterrupt:
        interrupted = True
    elapsed = time.monotonic() - started
    section = {
        "checked_at": started_wall.isoformat(), "model": str(args.model),
        "sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
        "device": args.device, "threshold": args.threshold, "vad_threshold": args.vad_threshold,
        "cooldown_seconds": args.cooldown, "requested_hours": args.hours,
        "measured_hours": round(elapsed / 3600, 6), "false_activations": len(triggers),
        "trigger_events": triggers, "interrupted": interrupted,
        "passed": not interrupted and elapsed >= 8 * 3600 and len(triggers) <= 1,
        "audio_saved": False,
    }
    result = _write(args.output, "background", section)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if section["passed"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Physical Hey-Mica acceptance")
    parser.add_argument("command", choices=("detections", "background"))
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default=None)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--vad-threshold", type=float, default=0.5)
    parser.add_argument("--cooldown", type=float, default=3.0)
    parser.add_argument("--window", type=float, default=3.0)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--source", default="operator-provided")
    parser.add_argument("--version", default="candidate")
    parser.add_argument("--license", default="unverified")
    args = parser.parse_args()
    args.model = args.model.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if not args.model.is_file() or args.model.suffix.casefold() != ".onnx":
        raise SystemExit("Ein existierendes lokales ONNX-Kandidatenmodell ist erforderlich.")
    if isinstance(args.device, str) and args.device.isdecimal():
        args.device = int(args.device)
    if args.command == "detections":
        return run_detections(args)
    return run_background(args)


if __name__ == "__main__":
    raise SystemExit(main())
