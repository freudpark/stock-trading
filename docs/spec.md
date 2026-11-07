# stock_bot spec (v1.1, 2026-11-05)

Status: **APPROVED (Gate 1, 2026-11-01); v1.1 changes approved 2026-11-05** (parts of Martin Luk's method, see §11). The user accepted the proposals for universe, exit and live capital. The KIS account and paper-trading (모의투자) application are **deferred**: development continues on a fake broker until they exist.

## 1. Goal
Korean stocks only (KOSPI/KOSDAQ). Research and pick candidates, decide with code rules, check every order against fixed risk rules, then execute through KIS (한국투자증권). Paper trading comes first; live money only after the gates below. No crypto.

## 2. Layers
| Layer | Who | Does | Does NOT |
|---|---|---|---|
| BRAIN | Claude (+ serenity-skill, knowledge-sources) | Market regime report, candidate list with thesis / bear case / invalidation, nightly review, rule-change proposals | Place orders, compute prices or sizes |
| REFLEX | Code (`strategy/`) | Per-bar signal from the state snapshot: regime, direction, signal quality 0–3, risk state | Call an LLM per bar |
| GUARD | Code (`risk/guard.py`) | Fixed rules checked before every order; cannot be overridden by any model | — |
| EXECUTION | Code (`execution/`, `broker/kis_client.py`) | Sizing, order placement, fills, logs | Decide direction |

An optional LLM filter (stage1) may run **once per day before the open**, on real fetched news and disclosures only. It is never called per bar.

## 3. Broker and data
- KIS Open API: **paper trading (모의투자) server first**, live server later. KIS account/모의투자 application: **deferred by the user**. Until then everything runs against `broker/fake_broker.py` and recorded/historical data.
- Prices and order book: KIS REST + WebSocket.
- Fundamentals and disclosures: OpenDART, KIND. History for backtests: KIS daily bars (or pykrx).
- Keys live in `.env` only (`KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ENV=paper|live`).

## 4. Universe
Approved: a watchlist of 10–20 liquid stocks (KOSPI200/KOSDAQ150 members, average daily value ≥ 10억원), refreshed weekly by BRAIN and approved by the user.

v1.1 screening, computed by code on daily bars before BRAIN reviews the list:
- Trend class from daily EMAs: **Lead** 9 > 21 > 50; **Lag** 9 < 21 < 50; **Mediocre** otherwise.
- Volatility: ADR (average daily range, 20 days) ≥ 3.5% (starting value).
- Liquidity: 20-day average traded value (price × volume) ≥ 10억원 (starting value).
- Ranking: Lead first, then 1-month return. Sector clustering (several stocks of one industry turning Lead in the same week) is flagged for BRAIN.
- Thresholds above are starting values taken from a US method; final values are set by backtest on KRX data, then approved.

## 5. Strategy (v1)
Volatility breakout (existing logic): target = today open + (prev high − prev low) × K, K = 0.5.
- Enter only when every condition holds: signal quality ≥ 2, regime ≠ 위기, risk state = 안전, and the BRAIN daily filter is not "회피".
- v1.1: Lead stocks raise signal quality by 1 (max 3); Lag stocks are not traded long.
- v1.1 regime input (market breadth): share of the watchlist in Lead. A drop in that share over the last 5 days moves the regime toward 횡보/위기 (exact mapping set in stage 3).
- Exit (approved): sell at 15:15 the same day (no overnight). Hard stop at −2% from entry.

## 6. Fixed risk rules (risk/limits.toml; checked before every order)
| Rule | Proposal |
|---|---|
| Max drawdown from peak equity | 15% → halt all trading until the user resets |
| Daily loss limit | 2% of equity → no new orders today |
| Risk per trade | 1% of equity (size = 1% ÷ stop distance) |
| Max weight per stock | 20% of equity |
| Max open positions | 5 |
| Kill switch | if file `~/stock_bot/STOP` exists → no orders, cancel open orders |
| Market hours | no new orders before 09:05 or after 15:10 |
| Korean market blocks | skip stocks in VI, trading halt, 관리종목/투자경고, within 3% of 상한가/하한가 |
| Order sanity | tick-size rounding, price within ±3% of last, quantity > 0, enough cash |
| Costs | include commission + securities transaction tax in P&L (rates to verify, 미검증) |
| Earnings (v1.1) | no new entry within 5 trading days before a scheduled earnings disclosure (DART 잠정실적 / IR 일정); unknown date → treat as unsafe only if BRAIN flags it |

Kelly sizing: **not used** until at least 200 paper trades give calibrated probabilities (Brier score). Fixed 1% risk until then.

## 7. Approval gates
- Development: each of the 6 stages needs user approval.
- Trading: MANUAL mode (every order approved in the dashboard or Telegram) is the default. AUTO is allowed **only on the paper server**, and on live only after Gate 6.
- Rule changes from the nightly review are proposals; they apply only after user approval.

## 8. Nightly review (16:00 KST)
Trades and skipped signals, P&L after costs, **R-multiple per trade (P&L ÷ initial risk) and expectancy in R**, hit rate, Brier score of signal-quality → outcome, guard rejections, anomalies. Report goes to Telegram (@s26SV_bot) and `reports/YYYY-MM-DD.md`.
v1.1: strategies are judged by expectancy in R and max losing streak, not by hit rate. A re-entry in the same stock on the same day is a separate trade, tagged 1st / 2nd / 3rd+, and measured separately.

## 9. Go-live gates
1. Backtest (no look-ahead, costs included) shows positive expectancy.
2. Paper trading for at least 1–3 months: positive after costs, max drawdown < 10%, zero guard bugs.
3. Live with small capital (approved: ≤ 100만원), MANUAL mode first.

## 10. Runtime
Needs an always-on machine. Phone (Termux) is fine for paper testing; live trading should wait for the Ubuntu laptop hub (plans/orchestra.md).

## 11. v1.1 notes (Martin Luk method, 2026-11-05)
Source: an X post summarizing a fan-made archive (martinluk.com, not official) of Martin Luk's streams. Claimed results (969.8% in USIC 2025, long hit rate ~17%) are 미검증.
- Adopted now: EMA trend classes, ADR/traded-value screening, earnings block, breadth as regime input, R-multiple journaling.
- Deferred to a v2 candidate strategy (needs a spec change because it holds overnight): pullback to a confluence of 9/21 EMA, prior box high and anchored VWAP, entry on a 5-minute range breakout, stop at the breakout candle low or day low, trail with 9/21 EMA. Backtest side by side with v1 first.
- Not adopted: short selling (out of scope), market orders as default (thin KRX order books; limit orders stay).
- Risk note: at a ~17% hit rate, 10 losses in a row has ~16% probability; at 1% risk per trade, 15 straight losses ≈ 14% drawdown, near the 15% halt. If v2 is adopted, risk per trade 0.5% is to be reviewed with it.
