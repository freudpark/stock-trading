"""Order service: guard → approval gate → broker, with every step journaled.

- Every order passes the guard. In MANUAL mode new entries wait for the user's
  approval (dashboard/Telegram) and are re-checked by the guard when approved;
  approvals expire after a few minutes because prices move.
- AUTO mode is refused on a live account (spec §7).
- Exits (sells that close held shares: 15:15 flatten, hard stop) skip the approval
  wait so they cannot be left hanging, but they still pass the guard.
- Client order ids make retries safe. If the broker's answer is lost, the order is
  looked up; if that also fails, the symbol is blocked until its state is known.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from broker.base import Broker
from core.clock import Clock
from core.types import Account, Order, OrderIntent, OrderStatus, Side
from journal.writer import Journal
from risk.guard import Guard, MarketContext

APPROVAL_TTL = timedelta(minutes=5)


class Mode(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"


@dataclass(frozen=True)
class Pending:
    approval_id: str
    intent: OrderIntent
    meta: dict
    created: datetime


@dataclass(frozen=True)
class Submission:
    status: str   # pending_approval | placed | rejected_by_guard | broker_rejected | declined
                  # | expired | error | rejected_unknown_state
    reasons: tuple[str, ...] = ()
    order: Order | None = None
    approval_id: str | None = None
    client_order_id: str | None = None


def _entry_label(n: int) -> str:
    return {1: "1st", 2: "2nd"}.get(n, "3rd+")


class OrderService:
    def __init__(self, broker: Broker, guard: Guard, journal: Journal, clock: Clock,
                 mode: Mode, live: bool, approval_ttl: timedelta = APPROVAL_TTL):
        if mode is Mode.AUTO and live:
            raise ValueError("AUTO mode is allowed only on paper/fake accounts")
        self.broker, self.guard, self.journal, self.clock = broker, guard, journal, clock
        self.mode, self.live, self.ttl = mode, live, approval_ttl
        self._pending: dict[str, Pending] = {}
        self._unknown: dict[str, str] = {}   # symbol → client order id with unknown state
        today = clock.now().date()
        self._seq = sum(1 for e in journal.read(today) if e.get("kind") in ("order", "approval_requested"))

    # ---- public ----
    def submit(self, intent: OrderIntent, account: Account, ctx: MarketContext,
               meta: dict | None = None, exit_order: bool = False) -> Submission:
        if exit_order and intent.side is not Side.SELL:
            raise ValueError("only sells can be exit orders")
        meta = dict(meta or {})
        blocked = self._resolve_unknown(intent.symbol)
        if blocked:
            return blocked
        g = self._guard(intent, account, ctx, meta)
        if not g.approved:
            return Submission("rejected_by_guard", g.reasons)
        if self.mode is Mode.MANUAL and not exit_order:
            aid = self._next_id(intent, "A")
            self._pending[aid] = Pending(aid, g.intent, meta, self.clock.now())
            self.journal.append("approval_requested", approval_id=aid, intent=g.intent, meta=meta)
            return Submission("pending_approval", approval_id=aid)
        return self._place(g.intent, meta)

    def pending(self) -> list[Pending]:
        return list(self._pending.values())

    def approve(self, approval_id: str, account: Account, ctx: MarketContext) -> Submission:
        p = self._pending.pop(approval_id)   # KeyError if unknown or already handled
        if self.clock.now() - p.created > self.ttl:
            self.journal.append("approval_expired", approval_id=approval_id)
            return Submission("expired", ("approval came too late; prices may have moved",), approval_id=approval_id)
        self.journal.append("approved", approval_id=approval_id)
        blocked = self._resolve_unknown(p.intent.symbol)
        if blocked:
            return blocked
        g = self._guard(p.intent, account, ctx, p.meta)
        if not g.approved:
            return Submission("rejected_by_guard", g.reasons, approval_id=approval_id)
        return self._place(g.intent, p.meta, approval_id)

    def reject(self, approval_id: str, why: str = "") -> Submission:
        self._pending.pop(approval_id)
        self.journal.append("declined", approval_id=approval_id, why=why)
        return Submission("declined", (why,) if why else (), approval_id=approval_id)

    def expire_stale(self) -> list[str]:
        now = self.clock.now()
        old = [a for a, p in self._pending.items() if now - p.created > self.ttl]
        for a in old:
            del self._pending[a]
            self.journal.append("approval_expired", approval_id=a)
        return old

    # ---- internals ----
    def _guard(self, intent, account, ctx, meta):
        g = self.guard.check(intent, account, ctx)
        self.journal.append("guard", symbol=intent.symbol, side=intent.side, qty=intent.qty,
                            limit_price=intent.limit_price, approved=g.approved, reasons=g.reasons, meta=meta)
        return g

    def _next_id(self, intent: OrderIntent, prefix: str = "O") -> str:
        self._seq += 1
        return f"{prefix}{self.clock.now():%Y%m%d-%H%M%S}-{intent.symbol}-{intent.side.value}-{self._seq:03d}"

    def _resolve_unknown(self, symbol: str) -> Submission | None:
        oid = self._unknown.get(symbol)
        if oid is None:
            return None
        try:
            order = self.broker.get_order(oid)
            self.journal.append("order_state_resolved", client_order_id=oid, status=order.status)
        except KeyError:
            self.journal.append("order_state_resolved", client_order_id=oid, status="not_placed")
        except Exception as e:
            reason = f"order {oid} state unknown ({type(e).__name__}); no new orders for {symbol}"
            self.journal.append("blocked_unknown_state", symbol=symbol, reason=reason)
            return Submission("rejected_unknown_state", (reason,))
        del self._unknown[symbol]
        return None

    def _entry_index(self, symbol: str) -> str:
        today = self.clock.now().date()
        n = sum(1 for e in self.journal.read(today) if e.get("kind") == "order" and e.get("symbol") == symbol
                and e.get("side") == Side.BUY.value and e.get("status") != OrderStatus.REJECTED.value)
        return _entry_label(n + 1)

    def _place(self, intent: OrderIntent, meta: dict, approval_id: str | None = None) -> Submission:
        oid = self._next_id(intent)
        extra = {}
        if intent.side is Side.BUY:
            extra = {"entry_index": self._entry_index(intent.symbol), "stop_price": intent.stop_price,
                     "initial_risk": (intent.limit_price - intent.stop_price) * intent.qty}
        try:
            order = self.broker.place_order(intent, oid)
        except Exception as e:
            self.journal.append("broker_error", client_order_id=oid, symbol=intent.symbol, error=type(e).__name__)
            try:
                order = self.broker.get_order(oid)
            except KeyError:
                return Submission("error", (f"broker error {type(e).__name__}; order not placed",),
                                  client_order_id=oid, approval_id=approval_id)
            except Exception:
                self._unknown[intent.symbol] = oid
                return Submission("error", (f"broker error {type(e).__name__}; order state unknown",),
                                  client_order_id=oid, approval_id=approval_id)
        self.journal.append("order", client_order_id=oid, symbol=intent.symbol, side=intent.side,
                            qty=intent.qty, limit_price=intent.limit_price, status=order.status,
                            filled_qty=order.filled_qty, avg_fill_price=order.avg_fill_price,
                            message=order.message, approval_id=approval_id, **extra, meta=meta)
        if order.status is OrderStatus.REJECTED:
            return Submission("broker_rejected", (order.message,), order, approval_id, oid)
        return Submission("placed", (), order, approval_id, oid)
