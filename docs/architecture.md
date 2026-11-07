# stock_bot architecture (v0.2, 2026-11-05)

Status: **APPROVED (Gate 2, 2026-11-05).** Risk per trade stays 1%; the v2 pullback strategy is deferred. Based on the approved spec v1.1 in `docs/spec.md`. v0.2 adds the v1.1 items (screener, EMA classes, earnings block, breadth, R-multiples).

## 1. Principles
1. **The model judges; code computes and executes.** No LLM inside the per-bar loop.
2. **The guard is last and absolute.** Every order passes `risk/guard.py`; no config flag or model output can bypass it.
3. **No look-ahead.** Every snapshot carries `as_of`; strategies may only see bars whose close time ≤ `as_of`. The backtester enforces the same rule.
4. **Broker behind an interface.** `FakeBroker` (now) and `KisBroker` (later, paper then live) implement the same methods, so the same code runs in tests, backtests, paper and live.
5. **Standard library first.** pandas does not build on Termux. The core uses only the Python stdlib (`tomllib`, `json`, `dataclasses`, `decimal`). The existing Flask dashboard stays as is.

## 2. Data flow (one bar)
```
broker.get_quote / bars ──► engine/state.py ──► Snapshot (numbers only, as_of)
                                                   │
                                   strategy/breakout.py ──► Signal (typed schema)
                                                   │
                      execution/sizing.py (1% risk rule) ──► OrderIntent
                                                   │
                         risk/guard.py (fixed rules) ──► APPROVED / REJECTED(reason)
                                                   │
                approval gate (MANUAL: dashboard/Telegram │ AUTO: paper only)
                                                   │
                            execution/order.py ──► broker.place_order
                                                   │
                           journal/ (every step appended as JSON lines)
```
Daily, outside the loop:
- 08:00 screener (`universe/screener.py`): EMA class, ADR, traded value, breadth → `data/screen/YYYY-MM-DD.json` (weekly run feeds the watchlist proposal)
- 08:30 BRAIN pre-open filter (optional): real news/disclosures → per-stock `허용 / 회피` (`brain/daily_filter.py`)
- 15:15 forced flat (`execution/flatten.py`)
- 16:00 nightly review (`review/nightly.py`) → Telegram + `reports/YYYY-MM-DD.md`

## 3. Modules and files
| Path | Responsibility |
|---|---|
| `config/settings.toml` | Mode (`fake`/`paper`/`live`), watchlist, schedule, K value |
| `risk/limits.toml` | Fixed risk numbers from the spec. Read-only at runtime |
| `core/types.py` | Dataclasses: `Bar`, `Quote`, `Snapshot`, `Signal`, `OrderIntent`, `GuardResult`, `Fill`, `Position` |
| `core/clock.py` | KST clock, market sessions, holidays; injectable for tests/backtests |
| `core/ticks.py` | KRX tick-size rounding, price-limit (±30%) helpers |
| `core/indicators.py` | EMA, ADR, traded value, EMA trend class (Lead/Mediocre/Lag), R-multiple. Pure functions on closed bars only |
| `universe/screener.py` | Applies the spec §4 filters to daily bars, ranks, flags sector clusters, computes breadth (share in Lead) |
| `data/earnings.py` | Upcoming earnings dates per stock from OpenDART/KIND, cached daily; used by the guard |
| `broker/base.py` | `Broker` protocol: `get_quote`, `get_daily_bars`, `get_balance`, `get_positions`, `place_order`, `cancel_order`, `get_status_flags` (VI, halt, warning) |
| `broker/fake_broker.py` | In-memory broker with simulated fills, costs and status flags; used by tests and backtests |
| `broker/kis_client.py` | KIS REST/WebSocket client (paper/live by env). **Built later** when the account exists |
| `engine/state.py` | Builds `Snapshot`: mid, spread, order-book imbalance, realized volatility, position, equity, drawdown. Numbers only, < 400 tokens when serialized |
| `strategy/schema.py` | Typed signal: regime {추세, 횡보, 고변동, 위기}, direction {롱, 중립}, quality 0–3, risk_state {안전, 한도근접, 축소}, reasons |
| `strategy/breakout.py` | Volatility-breakout rule → `Signal`; quality +1 for Lead, no long for Lag; regime uses breadth |
| `execution/sizing.py` | Quantity = (equity × 1%) ÷ stop distance, capped by 20% weight and cash |
| `risk/guard.py` | All fixed rules (drawdown 15%, daily 2%, max 5 positions, 20% weight, kill switch file, hours, VI/halt/warning/limit-band, price sanity, tick rounding, earnings within 5 trading days) → `GuardResult` |
| `execution/order.py` | Approval gate, then `broker.place_order`; idempotent client order ids |
| `execution/flatten.py` | 15:15 sell-all of intraday positions |
| `journal/` | Append-only JSONL: snapshots, signals, guard decisions, orders, fills; each trade stores initial stop, initial risk (R), entry index of the day (1st/2nd/3rd+), regime and breadth at entry |
| `review/nightly.py` | P&L after costs, R-multiples, expectancy in R, max losing streak, re-entry stats, hit rate, Brier score, guard rejections → report |
| `notify/telegram.py` | Sends via `~/.config/telegram/bot.env` (token never logged) |
| `brain/daily_filter.py` | Optional pre-open LLM filter on fetched sources; output is advisory and can only *block*, never *add* trades |
| `backtest/run.py` | Replays history through the same strategy + guard with `FakeBroker`; costs included; as_of enforced |
| `main.py` | Scheduler loop: sessions, polling, calls the pipeline, graceful stop |
| `tests/` | `unittest` (stdlib). Guard rules first (incl. earnings block), then sizing, ticks, indicators (EMA/ADR vs hand-computed values), screener, strategy, no-look-ahead, flatten |

Existing files: `trader.py`, `toss_api.py`, `agents/` and `app.py` stay untouched until the new pipeline replaces them in stage 6. `dashboard/` is later wired to `journal/` instead of hard-coded numbers.

## 4. Key decisions
| Decision | Choice | Why |
|---|---|---|
| Language/deps | Python stdlib core, `unittest` | Runs on Termux and the laptop; no pandas build issues |
| Config format | TOML (`tomllib`) | Stdlib, readable |
| Storage | JSONL files + daily Markdown reports | Simple, greppable, git-friendly; no DB to run |
| Money math | `Decimal` for prices/costs, int for quantities | Avoid float rounding on KRW and ticks |
| Kill switch | File `~/stock_bot/STOP` | Works from any shell or by Claude; no process signals needed |
| Notifications | Telegram @s26SV_bot | Already set up |

## 5. Failure handling
- Broker/API error → no order; log; retry only read calls.
- Unknown order state → query status before any new order for that symbol.
- Guard config missing or unreadable → refuse to trade (fail closed).
- Clock outside session → no orders.
- Process restart → rebuild positions from the broker (or the fake broker's journal) before trading.

## 6. Out of scope (v1)
Short selling, overnight holding (v2 candidate pullback strategy waits for a spec change), anchored VWAP and minute-bar entries (v2), margin/credit, options/futures, crypto, per-bar LLM calls, Kelly sizing.
