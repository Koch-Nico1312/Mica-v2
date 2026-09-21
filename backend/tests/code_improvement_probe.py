"""Manual acceptance probe for the promoted-code sandbox.

The shell orchestrates the security boundary in three distinct processes:
prepare the Git candidate, run the host-agent shadow check, then promote and
invoke the active labelled image. This helper only performs registry steps.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from services.common.brain import MarkdownBrain
from services.common.improvements import ImprovementRegistry


def registry(root: Path) -> ImprovementRegistry:
    os.environ["IMPROVEMENT_WORKSPACE"] = str(root / "improvement-workspace")
    brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
    return ImprovementRegistry(root / "improvements.sqlite3", brain)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "promote", "state"))
    parser.add_argument("--root", default="/data")
    parser.add_argument("--id", default="")
    args = parser.parse_args()
    root = Path(args.root)
    active = registry(root)
    if args.mode == "prepare":
        proposal = active.propose(
            "code-probe", "code",
            "def main(payload):\n"
            "    return {'healthcheck': bool(payload.get('healthcheck')), "
            "'echo': str(payload.get('echo', ''))[:80]}\n",
            "manual isolated code acceptance probe",
        )
        print(json.dumps(proposal, sort_keys=True))
        return
    if args.mode == "promote":
        if not args.id:
            raise SystemExit("--id is required")
        evaluated = active.evaluate(args.id, True, True, "shadow tests passed", "shadow health passed")
        promoted = active.promote(args.id) if evaluated else False
        print(json.dumps({"evaluated": evaluated, "promoted": promoted}, sort_keys=True))
        return
    print(json.dumps(active.runtime_state(), sort_keys=True))


if __name__ == "__main__":
    main()
