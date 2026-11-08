"""Daily KRX bars from Yahoo Finance's chart endpoint (unofficial, free, stdlib only).

Prices are Yahoo's split-adjusted OHLC (not dividend-adjusted), rounded to whole won.
Bad rows (missing values, impossible OHLC, a move beyond the ±30% daily band) are
dropped and reported. Today's bar is dropped until 15:30 KST (not closed yet).
Raw responses are cached so runs are reproducible and the endpoint is not hammered.
"""
from __future__ import annotations

import json
import time as _time
import urllib.request
from datetime import datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable

from core.clock import KST
from core.types import Bar

SUFFIX = {"KOSPI": "KS", "KOSDAQ": "KQ"}
CLOSE = time(15, 30)
MAX_MOVE = Decimal("0.30")
CACHE_HOURS = 12


def yahoo_symbol(code: str, market: str) -> str:
    if market not in SUFFIX:
        raise ValueError(f"market must be KOSPI or KOSDAQ, got {market!r}")
    return f"{code}.{SUFFIX[market]}"


def _won(x: float) -> Decimal:
    return Decimal(str(x)).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def parse_chart(payload: dict, code: str, now: datetime | None = None) -> tuple[list[Bar], list[str]]:
    chart = payload.get("chart") or {}
    results = chart.get("result")
    if not results:
        raise ValueError(f"{code}: no data ({(chart.get('error') or {}).get('code', 'unknown')})")
    r = results[0]
    q = r["indicators"]["quote"][0]
    bars: list[Bar] = []
    issues: list[str] = []
    prev_close: Decimal | None = None
    for i, ts in enumerate(r.get("timestamp") or []):
        day = datetime.fromtimestamp(ts, timezone.utc).astimezone(KST).date()
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in vals):
            issues.append(f"{day}: missing value")
            continue
        o, h, l, c = (_won(v) for v in vals[:4])
        v = int(vals[4])
        if not (0 < l <= min(o, c) and max(o, c) <= h) or v < 0:
            issues.append(f"{day}: impossible OHLC")
            continue
        if prev_close is not None and abs(c / prev_close - 1) > MAX_MOVE:
            issues.append(f"{day}: close moved more than 30% (data error)")
            continue
        close_time = datetime.combine(day, CLOSE, KST)
        if now is not None and close_time > now:
            continue  # not closed yet
        bars.append(Bar(code, day, o, h, l, c, v, close_time))
        prev_close = c
    return bars, issues


def fetch_daily(code: str, market: str, cache_dir: Path, now: datetime, years: int = 3,
                opener: Callable = urllib.request.urlopen, pause: float = 0.0) -> list[Bar]:
    """Bars for `years` years, using a cached response younger than CACHE_HOURS."""
    sym = yahoo_symbol(code, market)
    cache = Path(cache_dir) / f"{sym}_{years}y.json"
    fresh = cache.exists() and (_time.time() - cache.stat().st_mtime) < CACHE_HOURS * 3600
    if fresh:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        if pause:
            _time.sleep(pause)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={years}y&interval=1d"
        with opener(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as resp:
            payload = json.loads(resp.read())
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload), encoding="utf-8")
    bars, _ = parse_chart(payload, code, now)
    return bars
