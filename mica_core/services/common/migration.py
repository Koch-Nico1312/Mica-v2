from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .brain import MarkdownBrain


def migrate_legacy_memory(source: str | Path, brain: MarkdownBrain) -> dict[str, int | str]:
    """Losslessly archive legacy JSON, with individual Markdown entries for recall."""
    path = Path(source)
    raw = path.read_text(encoding="utf-8")
    data: Any = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("legacy memory must be a JSON object")
    snapshot = brain.write("migrations", "Legacy long_term.json snapshot", "```json\n" + raw + "\n```", {"source": path.name, "format": "long_term.json"})
    entries = 0
    for category, values in data.items():
        if isinstance(values, dict):
            for key, value in values.items():
                actual = value.get("value") if isinstance(value, dict) and "value" in value else value
                brain.write("memory", f"{category}: {key}", str(actual), {"legacy_category": str(category), "legacy_key": str(key)})
                entries += 1
        elif isinstance(values, list):
            for index, value in enumerate(values):
                brain.write("memory", f"{category}: {index + 1}", json.dumps(value, ensure_ascii=False), {"legacy_category": str(category), "legacy_index": index})
                entries += 1
    return {"entries": entries, "snapshot": snapshot["id"]}
