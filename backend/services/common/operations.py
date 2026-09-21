"""Local operational measurements and versioned price metadata."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
import uuid


PRICE_TABLE_VERSION = "2026-09-10.v1"
# No network price is guessed. Operators may add a verified per-million-unit
# price and source in a reviewed release; null means quantities only.
PRICE_TABLE: dict[str, dict[str, Any]] = {
    "local_llama": {"input_per_million": None, "output_per_million": None, "currency": None, "source": None},
    "openai_api": {"input_per_million": None, "output_per_million": None, "currency": None, "source": None},
    "gemini": {"input_per_million": None, "output_per_million": None, "currency": None, "source": None},
    "telegram": {"input_per_million": None, "output_per_million": None, "currency": None, "source": None},
    "whatsapp": {"input_per_million": None, "output_per_million": None, "currency": None, "source": None},
    "push": {"input_per_million": None, "output_per_million": None, "currency": None, "source": None},
    "sip": {"input_per_million": None, "output_per_million": None, "currency": None, "source": None},
}


class OperationLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS operations ("
                "id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, turn_id TEXT, task_id TEXT, "
                "action TEXT NOT NULL, provider TEXT NOT NULL, duration_ms INTEGER NOT NULL, "
                "error_class TEXT, retries INTEGER NOT NULL, external INTEGER NOT NULL, "
                "input_units INTEGER, output_units INTEGER, price_version TEXT NOT NULL, "
                "cost REAL, currency TEXT)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def record(
        self, *, action: str, provider: str, duration_ms: int, turn_id: str | None = None,
        task_id: str | None = None, error_class: str | None = None, retries: int = 0,
        external: bool = False, input_units: int | None = None, output_units: int | None = None,
    ) -> str:
        pricing = PRICE_TABLE.get(provider, {})
        input_price, output_price = pricing.get("input_per_million"), pricing.get("output_per_million")
        cost = None
        if input_price is not None and output_price is not None and input_units is not None and output_units is not None:
            cost = (input_units * float(input_price) + output_units * float(output_price)) / 1_000_000
        operation_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (operation_id, datetime.now(UTC).isoformat(), turn_id, task_id, action, provider,
                 max(0, int(duration_ms)), error_class, max(0, int(retries)), int(external),
                 input_units, output_units, PRICE_TABLE_VERSION, cost, pricing.get("currency")),
            )
        return operation_id

    def summary(self, hours: int = 24) -> dict[str, Any]:
        bounded = max(1, min(int(hours), 24 * 31))
        since = (datetime.now(UTC) - timedelta(hours=bounded)).isoformat()
        with self._connect() as connection:
            total, failures, retries, external, duration = connection.execute(
                "SELECT COUNT(*), SUM(error_class IS NOT NULL), SUM(retries), SUM(external), "
                "COALESCE(SUM(duration_ms), 0) FROM operations WHERE occurred_at >= ?", (since,),
            ).fetchone()
            units = connection.execute(
                "SELECT provider, COUNT(*), COALESCE(SUM(input_units), 0), "
                "COALESCE(SUM(output_units), 0), SUM(cost), MAX(currency) "
                "FROM operations WHERE occurred_at >= ? GROUP BY provider ORDER BY provider", (since,),
            ).fetchall()
        total = int(total or 0)
        return {
            "schema_version": 1, "window_hours": bounded, "requests": total,
            "failures": int(failures or 0), "failure_rate": (int(failures or 0) / total if total else 0.0),
            "retries": int(retries or 0), "external_calls": int(external or 0),
            "duration_ms": int(duration or 0), "price_table_version": PRICE_TABLE_VERSION,
            "providers": [
                {"provider": row[0], "requests": row[1], "input_units": row[2],
                 "output_units": row[3], "cost": row[4], "currency": row[5],
                 "price_verified": row[4] is not None}
                for row in units
            ],
            "pricing": json.loads(json.dumps(PRICE_TABLE)),
        }
