"""One-shot subprocess runner for a single allowlisted legacy action."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from contextlib import redirect_stdout
from io import StringIO

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.action_adapters import ActionUnavailable, execute


def main() -> int:
    try:
        raw = sys.stdin.read(1024 * 1024 + 1)
        if len(raw.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Runner input exceeds 1 MiB")
        request = json.loads(raw)
        if not isinstance(request, dict) or not isinstance(request.get("params", {}), dict):
            raise ValueError("Runner input must be an object")
        # Legacy actions occasionally print progress. Keep stdout a single JSON
        # document because it is the authenticated agent protocol.
        progress = StringIO()
        with redirect_stdout(progress):
            result = execute(str(request.get("action", "")), request.get("params", {}))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (ActionUnavailable, ValueError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)[:500]}, ensure_ascii=False))
        return 2
    except Exception as error:
        print(json.dumps({"ok": False, "error": f"Action failed: {error}"[:500]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
