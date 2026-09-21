"""Append-only Phase-0/1 everyday-use acceptance log.

This tool records only booleans and mode names. It does not store prompts,
answers, profile values, or audio.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path


DEFAULT_OUTPUT = Path(".mica-data/workspace/artifacts/phase1-everyday-use.jsonl")
ALL_MODES = {"personal", "technical", "monitoring"}


def _load(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def _summary(records: list[dict[str, object]], today: date) -> dict[str, object]:
    by_day = {str(item.get("day")): item for item in records}
    streak: list[dict[str, object]] = []
    cursor = today
    while str(cursor) in by_day:
        streak.append(by_day[str(cursor)])
        cursor -= timedelta(days=1)
    streak.reverse()

    def safe(item: dict[str, object]) -> bool:
        return all(bool(item.get(field)) for field in (
            "persona_correct", "profile_correct", "profile_private",
            "no_data_loss", "no_unauthorized_action", "no_critical_defect",
        ))

    def full_phase1_day(item: dict[str, object]) -> bool:
        return (
            safe(item)
            and bool(item.get("text_used"))
            and bool(item.get("voice_used"))
            and bool(item.get("restart_completed"))
            and set(item.get("modes", [])) == ALL_MODES
        )

    safe_streak = len(streak) >= 7 and all(safe(item) for item in streak[-7:])
    phase1_days = sum(full_phase1_day(item) for item in streak[-7:])
    return {
        "consecutive_days_ending_today": len(streak),
        "phase0_seven_safe_days_passed": safe_streak,
        "phase1_full_days_in_current_week": phase1_days,
        "phase1_three_full_days_passed": safe_streak and phase1_days >= 3,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Record one honest MICA everyday-use day")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--text", action="store_true")
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--mode", action="append", choices=sorted(ALL_MODES), default=[])
    parser.add_argument("--persona-ok", action="store_true")
    parser.add_argument("--profile-ok", action="store_true")
    parser.add_argument("--profile-private", action="store_true")
    parser.add_argument("--no-data-loss", action="store_true")
    parser.add_argument("--no-unauthorized-action", action="store_true")
    parser.add_argument("--no-critical-defect", action="store_true")
    args = parser.parse_args()

    today = date.today()
    output = args.output.expanduser().resolve()
    records = _load(output)
    if any(item.get("day") == str(today) for item in records):
        raise SystemExit(f"Für {today} existiert bereits ein Eintrag; Rückdatieren/Überschreiben ist gesperrt.")
    record: dict[str, object] = {
        "schema_version": 1,
        "day": str(today),
        "recorded_at_local": datetime.now().astimezone().isoformat(),
        "text_used": args.text,
        "voice_used": args.voice,
        "restart_completed": args.restart,
        "modes": sorted(set(args.mode)),
        "persona_correct": args.persona_ok,
        "profile_correct": args.profile_ok,
        "profile_private": args.profile_private,
        "no_data_loss": args.no_data_loss,
        "no_unauthorized_action": args.no_unauthorized_action,
        "no_critical_defect": args.no_critical_defect,
        "content_or_audio_saved": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    result = {"record": record, "summary": _summary([*records, record], today)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
