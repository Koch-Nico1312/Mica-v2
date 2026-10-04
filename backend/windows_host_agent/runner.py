"""One-shot subprocess runner for a single allowlisted legacy action."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from contextlib import redirect_stdout, nullcontext
from io import StringIO

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from desktop.core.action_adapters import ActionUnavailable, execute
from backend.windows_host_agent import history


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
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
            action, params = str(request.get("action", "")), request.get("params", {})
            # Compensation holds the same guard internally. Other file actions
            # keep it across snapshot, mutation and durable receipt completion.
            operation = str(params.get('action', params.get('mode', ''))).strip().lower()
            guard = nullcontext() if action == 'file_controller' and operation == 'undo_change' else history.action_guard(action)
            with guard:
                receipt = history.prepare(action, params)
                try:
                    result = execute(action, params)
                except Exception:
                    history.finish(receipt, False)
                    raise
                result['change_id'] = history.finish(receipt, True)
                result['undo'] = {'change_id': result['change_id'],
                                  'available': next((r['undo_available'] for r in history.list_receipts()
                                                     if r['id'] == result['change_id']), False)}
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
