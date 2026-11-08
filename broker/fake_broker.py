"""In-memory broker for tests and backtests. No real money, no network.

Fill model (deliberately simple and a little pessimistic):
- Limit buy fills when ask <= limit, at the ask; limit sell fills when bid >= limit, at the bid.
- Each quote offers only its displayed size (ask_size / bid_size); the rest stays open.
- Resting orders are re-checked on every new quote.
- Commission on both sides, securities tax on sells, both truncated to whole won
  (원 미만 절사, 미검증 against KIS).
- Open buys hold cash; open sells hold shares (no short selling).
"""
from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal

from core import ticks
from core.clock import Clock
from core.types import (Balance, Bar, Fill, Order, OrderIntent, OrderStatus, Position, Quote,
                        Side, StatusFlags)


def _won(x: Decimal) -> Decimal:
    return x.to_integral_value(rounding=ROUND_FLOOR)


class FakeBroker:
    def __init__(self, cash: Decimal, clock: Clock, commission: Decimal, sell_tax: Decimal):
        self._cash = cash
        self._clock = clock
        self._commission = commission
        self._sell_tax = sell_tax
        self._quotes: dict[str, Quote] = {}
        self._flags: dict[str, StatusFlags] = {}
        self._prev_close: dict[str, Decimal] = {}
        self._bars: dict[str, list[Bar]] = {}
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._fills: list[Fill] = []

    # ---- market data feed (test/backtest side) ----
    def set_quote(self, quote: Quote) -> None:
        self._quotes[quote.symbol] = quote
        for o in list(self._orders.values()):
            if o.status is OrderStatus.OPEN and o.intent.symbol == quote.symbol:
                self._try_fill(o.order_id)

    def set_flags(self, symbol: str, flags: StatusFlags) -> None:
        self._flags[symbol] = flags

    def set_prev_close(self, symbol: str, prev_close: Decimal) -> None:
        self._prev_close[symbol] = prev_close

    def set_daily_bars(self, symbol: str, bars: list[Bar]) -> None:
        self._bars[symbol] = sorted(bars, key=lambda b: b.close_time)

    # ---- Broker protocol ----
    def get_quote(self, symbol: str) -> Quote | None:
        return self._quotes.get(symbol)

    def get_daily_bars(self, symbol: str) -> list[Bar]:
        now = self._clock.now()
        return [b for b in self._bars.get(symbol, []) if b.close_time <= now]

    def get_balance(self) -> Balance:
        held = sum((self._reserved_cash(o) for o in self._orders.values()
                    if o.status is OrderStatus.OPEN and o.intent.side is Side.BUY), Decimal(0))
        value = Decimal(0)
        for p in self._positions.values():
            q = self._quotes.get(p.symbol)
            value += p.qty * (q.last if q else p.avg_price)
        return Balance(cash=self._cash, available_cash=self._cash - held, equity=self._cash + value)

    def get_positions(self) -> dict[str, Position]:
        return dict(self._positions)

    def get_status_flags(self, symbol: str) -> StatusFlags:
        f = self._flags.get(symbol, StatusFlags())
        if f.upper_limit is None and symbol in self._prev_close:
            up, low = ticks.price_limits(self._prev_close[symbol])
            f = replace(f, upper_limit=up, lower_limit=low)
        return f

    def place_order(self, intent: OrderIntent, client_order_id: str) -> Order:
        existing = self._orders.get(client_order_id)
        if existing is not None:
            if existing.intent != intent:
                raise ValueError(f"order id {client_order_id} reused for a different order")
            return existing
        reason = self._reject_reason(intent)
        status = OrderStatus.REJECTED if reason else OrderStatus.OPEN
        self._orders[client_order_id] = Order(client_order_id, intent, status, message=reason,
                                              created=self._clock.now())
        if not reason:
            self._try_fill(client_order_id)
        return self._orders[client_order_id]

    def cancel_order(self, client_order_id: str) -> Order:
        o = self._orders[client_order_id]  # KeyError for unknown ids
        if o.status is OrderStatus.OPEN:
            o = replace(o, status=OrderStatus.CANCELLED)
            self._orders[client_order_id] = o
        return o

    def cancel_all(self) -> None:
        for o in self.open_orders():
            self.cancel_order(o.order_id)

    def get_order(self, client_order_id: str) -> Order:
        return self._orders[client_order_id]

    def open_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status is OrderStatus.OPEN]

    def get_fills(self) -> list[Fill]:
        return list(self._fills)

    fills = get_fills

    # ---- internals ----
    def _reserved_cash(self, o: Order) -> Decimal:
        return o.intent.limit_price * (o.intent.qty - o.filled_qty) * (1 + self._commission)

    def _reject_reason(self, intent: OrderIntent) -> str:
        if intent.qty <= 0:
            return "quantity must be > 0"
        if not ticks.is_valid_price(intent.limit_price):
            return "price not on a valid tick"
        if intent.symbol not in self._quotes:
            return "no quote for symbol"
        if self._flags.get(intent.symbol, StatusFlags()).halted:
            return "trading halt"
        if intent.side is Side.BUY:
            need = intent.limit_price * intent.qty * (1 + self._commission)
            if need > self.get_balance().available_cash:
                return "not enough cash"
        else:
            held = self._positions.get(intent.symbol)
            pending = sum(o.intent.qty - o.filled_qty for o in self.open_orders()
                          if o.intent.symbol == intent.symbol and o.intent.side is Side.SELL)
            if intent.qty + pending > (held.qty if held else 0):
                return "sell exceeds held shares"
        return ""

    def _try_fill(self, order_id: str) -> None:
        o = self._orders[order_id]
        it, q = o.intent, self._quotes.get(o.intent.symbol)
        if q is None:
            return
        if it.side is Side.BUY:
            if q.ask > it.limit_price:
                return
            price, size = q.ask, q.ask_size
        else:
            if q.bid < it.limit_price:
                return
            price, size = q.bid, q.bid_size
        qty = min(it.qty - o.filled_qty, size)
        if qty <= 0:
            return
        gross = price * qty
        commission = _won(gross * self._commission)
        tax = _won(gross * self._sell_tax) if it.side is Side.SELL else Decimal(0)
        self._apply_position(it.symbol, it.side, qty, price)
        self._cash += -gross - commission if it.side is Side.BUY else gross - commission - tax
        self._fills.append(Fill(order_id, it.symbol, it.side, qty, price, commission, tax,
                                self._clock.now()))
        filled = o.filled_qty + qty
        avg = price if o.avg_fill_price is None else (
            (o.avg_fill_price * o.filled_qty + price * qty) / filled)
        status = OrderStatus.FILLED if filled == it.qty else OrderStatus.OPEN
        self._orders[order_id] = replace(o, filled_qty=filled, avg_fill_price=avg, status=status)

    def _apply_position(self, symbol: str, side: Side, qty: int, price: Decimal) -> None:
        p = self._positions.get(symbol)
        if side is Side.BUY:
            if p is None:
                self._positions[symbol] = Position(symbol, qty, price)
            else:
                total = p.qty + qty
                self._positions[symbol] = Position(symbol, total, (p.avg_price * p.qty + price * qty) / total)
        else:
            left = p.qty - qty
            if left == 0:
                del self._positions[symbol]
            else:
                self._positions[symbol] = replace(p, qty=left)
