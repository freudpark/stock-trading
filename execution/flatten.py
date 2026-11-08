"""Exits: the 15:15 forced flat and the −2% hard stop (docs/spec.md §5).

Exit sells are marketable limits a little below the bid (EXIT_SLIP), so they fill
in the fake broker and normally in KRX, while the guard still checks the price.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from broker.base import Broker
from core.types import Account, OrderIntent, Side
from execution.order import OrderService, Submission
from risk.guard import MarketContext

EXIT_SLIP = Decimal("0.01")


def _sell_all(broker: Broker, svc: OrderService, account: Account,
              ctx_for: Callable[[str], MarketContext], symbol: str, why: str) -> Submission:
    for o in broker.open_orders():
        if o.intent.symbol == symbol:
            broker.cancel_order(o.order_id)
    pos = broker.get_positions()[symbol]
    ctx = ctx_for(symbol)
    price = ctx.quote.bid * (1 - EXIT_SLIP)
    intent = OrderIntent(symbol, Side.SELL, pos.qty, price, reason=why)
    return svc.submit(intent, account, ctx, meta={"exit": why}, exit_order=True)


def flatten_all(broker: Broker, svc: OrderService, account: Account,
                ctx_for: Callable[[str], MarketContext]) -> list[Submission]:
    """Cancel every open order, then sell every position."""
    for o in broker.open_orders():
        broker.cancel_order(o.order_id)
    symbols = sorted(broker.get_positions())
    svc.journal.append("flatten", symbols=symbols)
    return [_sell_all(broker, svc, account, ctx_for, s, "15:15 flatten") for s in symbols]


def stops_from_journal(entries: list[dict]) -> dict[str, Decimal]:
    """Latest stop price per symbol from today's placed buy orders."""
    stops: dict[str, Decimal] = {}
    for e in entries:
        if e.get("kind") == "order" and e.get("side") == "buy" and e.get("status") != "rejected" and e.get("stop_price"):
            stops[e["symbol"]] = Decimal(e["stop_price"])
    return stops


def stop_exits(broker: Broker, svc: OrderService, account: Account,
               ctx_for: Callable[[str], MarketContext], stops: dict[str, Decimal]) -> list[Submission]:
    """Sell any position whose last price is at or below its stop."""
    out = []
    for symbol in sorted(broker.get_positions()):
        stop = stops.get(symbol)
        q = broker.get_quote(symbol)
        if stop is not None and q is not None and q.last <= stop:
            out.append(_sell_all(broker, svc, account, ctx_for, symbol, f"hard stop {stop}"))
    return out
