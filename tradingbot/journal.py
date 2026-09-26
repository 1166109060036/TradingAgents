"""Append-only record of every decision and order the bot made."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, entry: dict) -> dict:
        entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def decided_on(self, ticker: str, trade_date: str) -> bool:
        """Whether a non-dry run already reached a decision for this ticker and date."""
        return any(
            e.get("ticker") == ticker and e.get("trade_date") == trade_date
            and e.get("executed") and e.get("rating")
            for e in self.entries()
        )
