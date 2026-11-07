"""Typed signal: the only thing the strategy hands to execution (docs/architecture.md)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.types import Direction, Regime, RiskState

MIN_QUALITY_TO_ENTER = 2


@dataclass(frozen=True)
class Signal:
    symbol: str
    as_of: datetime
    regime: Regime
    direction: Direction
    quality: int                 # 0–3
    risk_state: RiskState
    reasons: tuple[str, ...]
    target_price: Decimal | None = None
    entry_price: Decimal | None = None   # suggested limit price
    stop_price: Decimal | None = None    # initial stop (defines 1R)
    avoid: bool = False                  # BRAIN daily filter said 회피

    def __post_init__(self):
        if not isinstance(self.quality, int) or not 0 <= self.quality <= 3:
            raise ValueError(f"quality must be 0-3, got {self.quality!r}")
        for name, enum in (("regime", Regime), ("direction", Direction), ("risk_state", RiskState)):
            if not isinstance(getattr(self, name), enum):
                raise ValueError(f"{name} must be a {enum.__name__}")
        if self.direction is Direction.LONG:
            if self.entry_price is None or self.stop_price is None:
                raise ValueError("a long signal needs entry and stop prices")
            if not 0 < self.stop_price < self.entry_price:
                raise ValueError("stop must be below entry")

    @property
    def should_enter(self) -> bool:
        """Spec §5: quality ≥ 2, regime ≠ 위기, risk state 안전, BRAIN not 회피."""
        return (self.direction is Direction.LONG
                and self.quality >= MIN_QUALITY_TO_ENTER
                and self.regime is not Regime.CRISIS
                and self.risk_state is RiskState.SAFE
                and not self.avoid)
