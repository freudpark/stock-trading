"""Nightly review (docs/spec.md §8), built only from the journal.

A trade starts with the first buy fill while flat and ends when the position is
back to zero; a re-entry the same day is a new trade (tagged 1st / 2nd / 3rd+).
Strategies are judged by expectancy in R and max losing streak, not hit rate.
Brier score uses p(win) = signal quality / 3 as a starting mapping.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable

ANOMALY_KINDS = ("broker_error", "journal_error", "blocked_unknown_state", "approval_expired")


@dataclass
class Trade:
    symbol: str
    opened: str
    entry_index: str | None
    quality: int | None
    regime: str | None
    initial_risk: Decimal | None
    qty: int = 0                 # shares bought in this trade
    bought: Decimal = Decimal(0)  # gross
    sold: Decimal = Decimal(0)
    costs: Decimal = Decimal(0)
    closed: bool = False
    closed_at: str | None = None
    _open_qty: int = field(default=0, repr=False)

    @property
    def pnl(self) -> Decimal:
        return self.sold - self.bought - self.costs

    @property
    def r(self) -> Decimal | None:
        return self.pnl / self.initial_risk if self.initial_risk else None


@dataclass(frozen=True)
class Summary:
    count: int
    pnl: Decimal
    hit_rate: Decimal | None
    expectancy_r: Decimal | None
    max_losing_streak: int
    brier: Decimal | None
    by_entry: dict[str, tuple[int, Decimal | None]]


def build_trades(entries: Iterable[dict]) -> list[Trade]:
    entries = list(entries)
    orders = {e["client_order_id"]: e for e in entries if e.get("kind") == "order" and "client_order_id" in e}
    fills = sorted((e["fill"] for e in entries if e.get("kind") == "fill"), key=lambda f: f["time"])
    open_by_symbol: dict[str, Trade] = {}
    trades: list[Trade] = []
    for f in fills:
        sym, qty, px = f["symbol"], int(f["qty"]), Decimal(f["price"])
        cost = Decimal(f["commission"]) + Decimal(f["tax"])
        t = open_by_symbol.get(sym)
        if f["side"] == "buy":
            if t is None:
                o = orders.get(f["order_id"], {})
                meta = o.get("meta") or {}
                risk = o.get("initial_risk")
                t = Trade(sym, f["time"], o.get("entry_index"), meta.get("quality"), meta.get("regime"),
                          Decimal(risk) if risk else None)
                open_by_symbol[sym] = t
                trades.append(t)
            t.qty += qty
            t._open_qty += qty
            t.bought += px * qty
        else:
            if t is None:
                continue  # sell with no recorded entry: shows up as an anomaly, not a trade
            t.sold += px * qty
            t._open_qty -= qty
        t.costs += cost
        if t._open_qty <= 0:
            t.closed, t.closed_at = True, f["time"]
            del open_by_symbol[sym]
    return trades


def summarize(trades: Iterable[Trade]) -> Summary:
    done = sorted((t for t in trades if t.closed), key=lambda t: t.opened)
    if not done:
        return Summary(0, Decimal(0), None, None, 0, None, {})
    wins = [t.pnl > 0 for t in done]
    rs = [t.r for t in done if t.r is not None]
    streak = worst = 0
    for w in wins:
        streak = 0 if w else streak + 1
        worst = max(worst, streak)
    scored = [(Decimal(t.quality) / 3, Decimal(1 if t.pnl > 0 else 0)) for t in done if t.quality is not None]
    by: dict[str, list[Decimal]] = defaultdict(list)
    counts: Counter = Counter()
    for t in done:
        key = t.entry_index or "?"
        counts[key] += 1
        if t.r is not None:
            by[key].append(t.r)
    return Summary(
        count=len(done),
        pnl=sum((t.pnl for t in done), Decimal(0)),
        hit_rate=Decimal(sum(wins)) / len(done),
        expectancy_r=sum(rs, Decimal(0)) / len(rs) if rs else None,
        max_losing_streak=worst,
        brier=sum(((p - o) ** 2 for p, o in scored), Decimal(0)) / len(scored) if scored else None,
        by_entry={k: (counts[k], (sum(by[k], Decimal(0)) / len(by[k])) if by[k] else None) for k in sorted(counts)},
    )


def _r(x: Decimal | None) -> str:
    return "—" if x is None else f"{x:+.2f}R"


def _won(x: Decimal) -> str:
    return f"{x:+,.0f}원"


def _summary_lines(s: Summary) -> list[str]:
    if s.count == 0:
        return ["- 거래 없음"]
    lines = [f"- 거래 {s.count}건, 손익(비용 차감) {_won(s.pnl)}",
             f"- 기대값 {_r(s.expectancy_r)}, 최대 연속 손실 {s.max_losing_streak}회, 승률 {s.hit_rate:.0%}",
             f"- Brier {'—' if s.brier is None else f'{s.brier:.3f}'} (낮을수록 신호 품질이 결과를 잘 예측)"]
    lines += [f"- {k} 진입: {n}건, 평균 {_r(m)}" for k, (n, m) in s.by_entry.items()]
    return lines


def render_report(day: date, entries: list[dict], cumulative: list[Trade], open_positions: list[str]) -> str:
    today = build_trades(entries)
    out = [f"# stock_bot 일일 리뷰 {day.isoformat()}", "", "## 오늘 거래"]
    if today:
        out += ["| 종목 | 진입 | 품질 | 수량 | 손익 | R |", "|---|---|---|---|---|---|"]
        out += [f"| {t.symbol} | {t.entry_index or '?'} | {t.quality if t.quality is not None else '?'} | {t.qty} "
                f"| {_won(t.pnl) if t.closed else '미청산'} | {_r(t.r) if t.closed else '—'} |" for t in today]
    out += [""] + _summary_lines(summarize(today))

    skipped = sum(1 for e in entries if e.get("kind") == "signal" and e.get("direction") == "롱"
                  and not e.get("should_enter"))
    rejections = Counter(r for e in entries if e.get("kind") == "guard" and not e.get("approved")
                         for r in e.get("reasons") or [])
    out += ["", "## 신호와 거절", f"- 건너뛴 신호 {skipped}건"]
    out += [f"- 가드 거절: {reason} ×{n}" for reason, n in rejections.most_common()] or ["- 가드 거절 없음"]

    anomalies = [e for e in entries if e.get("kind") in ANOMALY_KINDS]
    out += ["", "## 이상 징후"]
    if open_positions:
        out.append(f"- ⚠ 장 마감 후 남은 보유: {', '.join(open_positions)}")
    out += [f"- {e['kind']}: {e.get('symbol') or e.get('client_order_id') or e.get('approval_id') or ''}"
            for e in anomalies]
    if not open_positions and not anomalies:
        out.append("- 없음")

    out += ["", "## 누적"] + _summary_lines(summarize(cumulative))
    return "\n".join(out) + "\n"


def write_report(day: date, text: str, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{day.isoformat()}.md"
    p.write_text(text, encoding="utf-8")
    return p
