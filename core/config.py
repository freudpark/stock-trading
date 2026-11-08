"""Loads config/settings.toml. Bad or missing settings raise ConfigError (fail closed)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from risk.guard import ConfigError

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    root: Path
    broker: str
    order_mode: str
    starting_cash: Decimal
    journal_dir: Path
    reports_dir: Path
    screen_dir: Path
    equity_state: Path
    earnings_file: Path
    screen_time: time
    flatten_time: time
    review_time: time
    holidays: frozenset[date]


def _time(v, key) -> time:
    try:
        hh, mm = str(v).split(":")
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        raise ConfigError(f"{key} must be HH:MM") from None


def load_settings(path: Path | None = None, root: Path = ROOT) -> Settings:
    path = Path(path or root / "config" / "settings.toml")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        paths, sched, cal = raw["paths"], raw["schedule"], raw["calendar"]
        broker, mode = raw["broker"], raw["order_mode"]
        if broker not in ("fake", "paper", "live"):
            raise ConfigError(f"broker must be fake/paper/live, got {broker!r}")
        if mode not in ("manual", "auto"):
            raise ConfigError(f"order_mode must be manual/auto, got {mode!r}")
        holidays = frozenset(date.fromisoformat(d) for d in cal["holidays_confirmed"] + cal["holidays_unverified"])
        return Settings(
            root=root, broker=broker, order_mode=mode,
            starting_cash=Decimal(str(raw["starting_cash"])),
            journal_dir=root / paths["journal"], reports_dir=root / paths["reports"],
            screen_dir=root / paths["screen"], equity_state=root / paths["equity_state"],
            earnings_file=root / paths["earnings"],
            screen_time=_time(sched["screen"], "schedule.screen"),
            flatten_time=_time(sched["flatten"], "schedule.flatten"),
            review_time=_time(sched["review"], "schedule.review"),
            holidays=holidays,
        )
    except ConfigError:
        raise
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"settings unreadable: {path}: {type(e).__name__} {e}") from None
