"""Append-only JSONL journal: one file per trading day, one JSON object per line.

Every pipeline step (snapshot, signal, guard decision, approval, order, fill, error)
is written here; the nightly review reads it back. Lines are never rewritten.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from core.clock import Clock


def _plain(v):
    if is_dataclass(v) and not isinstance(v, type):
        return {k: _plain(x) for k, x in asdict(v).items()}
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


class Journal:
    def __init__(self, directory: Path, clock: Clock):
        self.dir = Path(directory)
        self.clock = clock

    def path_for(self, day: date) -> Path:
        return self.dir / f"{day.isoformat()}.jsonl"

    def append(self, kind: str, **data) -> dict:
        now = self.clock.now()
        entry = {"t": now.isoformat(), "kind": kind, **_plain(data)}
        self.dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with open(self.path_for(now.date()), "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return entry

    def read(self, day: date) -> list[dict]:
        p = self.path_for(day)
        if not p.exists():
            return []
        out = []
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # a torn last line after a crash: keep what is readable, say so
                    out.append({"kind": "journal_error", "line": n})
        return out
