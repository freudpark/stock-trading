"""Daily screener (docs/spec.md §4): trend class, ADR, traded value, ranking,
sector clusters and market breadth. Runs before the open on closed daily bars only.

Thresholds are starting values from a US method; stage 5 backtests set the final ones.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

from core import indicators as ind
from core.clock import to_kst
from core.types import Bar, TrendClass
from engine.state import LookAheadError

MIN_ADR_PCT = Decimal("3.5")
MIN_TRADED_VALUE = Decimal(1_000_000_000)   # 10억원
MONTH = 21                                   # trading days
CLUSTER_WINDOW = 5                           # "turned Lead this week"
CLUSTER_MIN = 2
_RANK = {TrendClass.LEAD: 0, TrendClass.MEDIOCRE: 1}


@dataclass(frozen=True)
class Row:
    symbol: str
    trend: TrendClass | None
    adr_pct: Decimal | None
    traded_value: Decimal | None
    ret_1m_pct: Decimal | None
    passed: bool
    reasons: tuple[str, ...]
    sector: str | None = None


@dataclass(frozen=True)
class ScreenResult:
    as_of: datetime
    rows: list[Row]
    candidates: list[Row]                 # passed, ranked: Lead first, then 1-month return
    breadth_now: Decimal | None           # % of the universe in Lead
    breadth_5d_ago: Decimal | None
    clusters: dict[str, list[str]] = field(default_factory=dict)


def breadth(universe: Mapping[str, Sequence[Bar]], days_ago: int = 0) -> Decimal | None:
    """Share (%) of symbols whose trend class is Lead, using bars up to `days_ago` bars back.
    Symbols without enough history are left out; None if no symbol qualifies."""
    classes = [ind.trend_class(bars[:len(bars) - days_ago] if days_ago else bars)
               for bars in universe.values()]
    known = [c for c in classes if c is not None]
    if not known:
        return None
    return Decimal(sum(c is TrendClass.LEAD for c in known)) * 100 / len(known)


def _row(symbol: str, bars: Sequence[Bar], sector: str | None) -> Row:
    trend = ind.trend_class(bars)
    adr = ind.adr_pct(bars)
    value = ind.avg_traded_value(bars)
    ret = (bars[-1].close / bars[-1 - MONTH].close - 1) * 100 if len(bars) > MONTH else None
    reasons: list[str] = []
    if trend is None:
        reasons.append("not enough history (< 50 bars)")
    elif trend is TrendClass.LAG:
        reasons.append("trend Lag: no long")
    if adr is None or adr < MIN_ADR_PCT:
        reasons.append(f"ADR below {MIN_ADR_PCT}%")
    if value is None or value < MIN_TRADED_VALUE:
        reasons.append("traded value below 10억원")
    return Row(symbol, trend, adr, value, ret, not reasons, tuple(reasons), sector)


def screen(universe: Mapping[str, Sequence[Bar]], as_of: datetime,
           sectors: Mapping[str, str] | None = None) -> ScreenResult:
    as_of = to_kst(as_of)
    sectors = sectors or {}
    clean: dict[str, list[Bar]] = {}
    for sym, bars in universe.items():
        if any(to_kst(b.close_time) > as_of for b in bars):
            raise LookAheadError(f"{sym}: bar closes after as_of {as_of}")
        clean[sym] = sorted(bars, key=lambda b: b.close_time)

    rows = [_row(s, b, sectors.get(s)) for s, b in clean.items()]
    candidates = sorted((r for r in rows if r.passed),
                        key=lambda r: (_RANK[r.trend], -(r.ret_1m_pct or Decimal(0))))

    turned: dict[str, list[str]] = {}
    for s, bars in clean.items():
        if s in sectors and len(bars) > CLUSTER_WINDOW:
            now, before = ind.trend_class(bars), ind.trend_class(bars[:-CLUSTER_WINDOW])
            if now is TrendClass.LEAD and before is not TrendClass.LEAD:
                turned.setdefault(sectors[s], []).append(s)
    clusters = {k: sorted(v) for k, v in turned.items() if len(v) >= CLUSTER_MIN}

    return ScreenResult(as_of, rows, candidates, breadth(clean), breadth(clean, CLUSTER_WINDOW), clusters)


def save(result: ScreenResult, out_dir: Path) -> Path:
    """Write data/screen/YYYY-MM-DD.json style output; returns the path."""
    def num(x):
        return None if x is None else float(round(x, 4))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.as_of.date().isoformat()}.json"
    data = {
        "as_of": result.as_of.isoformat(),
        "breadth_now": num(result.breadth_now),
        "breadth_5d_ago": num(result.breadth_5d_ago),
        "candidates": [r.symbol for r in result.candidates],
        "clusters": result.clusters,
        "rows": [{"symbol": r.symbol, "sector": r.sector, "trend": r.trend.value if r.trend else None,
                  "adr_pct": num(r.adr_pct), "traded_value": num(r.traded_value),
                  "ret_1m_pct": num(r.ret_1m_pct), "passed": r.passed, "reasons": list(r.reasons)}
                 for r in result.rows],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
