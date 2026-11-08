# TODO

Contents: Goal · Phase A · Phase B (stages 1–6) · Stage 3 plan (3.1 open decisions, 3.2 build order, 3.3 verify) · Review

## Goal
Apply the quant-agent prompt's principles to Korean stocks: first fix security holes, then rebuild stock_bot on KIS (한국투자증권) with a hard risk guard, approval gates, and paper trading before any live money.

## Phase A: Security fixes (small, now)
- [x] A1. Dashboard (`dashboard/app.py`, `dashboard/index.html`): require a token (env `DASHBOARD_TOKEN`) for every POST; bind to 127.0.0.1 by default (env `DASHBOARD_HOST` to override); refuse to start without a token
- [x] A2. `app.py` (port 5000): same token on `/api/execute_trade`, 127.0.0.1 by default
- [x] A3. `agents/stage1_analyzer.py`: send the Gemini key in the `x-goog-api-key` header, not the URL
- [x] A4. `trader.py`, `toss_api.py`: do not log or return raw broker response bodies; return status code plus a short, sanitized message
- [x] A5. `.gitignore`: lines with leading spaces don't match; fix them
- Verify: run the dashboard in a venv; POST without token → 401, with token → 200; py_compile all changed files; grep shows no `?key=`

## Phase B: Six-stage rebuild (one approval gate per stage)
1. [x] Spec: `docs/spec.md` (v1.0 approved 2026-11-01; v1.1 approved 2026-11-05; KIS account deferred → fake broker)
2. [x] Architecture: `docs/architecture.md` v0.2 approved 2026-11-05 (Gate 2). Risk per trade stays 1%; v2 pullback strategy deferred.
3. [x] Plan: this file, section "Stage 3 plan" below. Approved 2026-11-05 (Gate 3), D1–D4 as proposed.
4. [x] Test-first implementation (order in 3.2). Done 2026-11-08, 182 tests pass. **Waiting for Gate 4.**
5. [ ] Review: backtest with no look-ahead (`backtest/`), security review
6. [ ] Ship: KIS paper trading for 1–3 months, then small live

## Stage 3 plan

### 3.1 Decisions needed at Gate 3 (proposed defaults)
- D1. Breadth → regime (spec §5 left this to stage 3). Breadth = share of the watchlist in Lead. Starting values, tuned in stage 5:
  - 위기: breadth < 20%, or breadth fell ≥ 20 percentage points over 5 trading days
  - 횡보: breadth 20–40%, or fell 10–20 points over 5 days
  - 추세: breadth ≥ 40% and not falling ≥ 10 points
  - 고변동 (per stock, overrides 추세/횡보): today's range so far > 2 × the stock's ADR
- D2. Earnings dates: in stage 4 read them from a hand-kept file `data/earnings_manual.json`; the OpenDART fetcher comes later and needs a free DART API key (new external service, ask then).
- D3. Costs: commission and securities transaction tax are config values in `risk/limits.toml`; real rates checked against KIS/KRX before stage 5 (미검증 until then).
- D4. Historical bars for the backtest: decided at stage 5 (pykrx is a new dependency; KIS daily bars need the account).

### 3.2 Build order (each step: write tests first, then code, then `python -m unittest`)
If a step's tests cannot pass without changing an earlier step's interface, stop and go back to that step.
1. `core/types.py`, `core/clock.py` (KST sessions, holidays list in config), `core/ticks.py` (KRX tick table, ±30% band)
2. `risk/limits.toml` + `risk/guard.py` — every rule in spec §6, fail closed on missing/bad config, kill switch file
3. `execution/sizing.py` — 1% risk ÷ stop distance, capped by 20% weight and cash, rounded down to whole shares
4. `core/indicators.py` — EMA, ADR, traded value, Lead/Mediocre/Lag, R-multiple; checked against hand-computed values
5. `broker/base.py` + `broker/fake_broker.py` — fills, costs, status flags (VI/halt/warning)
6. `engine/state.py` — Snapshot with `as_of`; refuses bars that close after `as_of`
7. `strategy/schema.py` + `strategy/breakout.py` — K = 0.5, quality rules, Lag = no long, regime from D1
8. `universe/screener.py` — spec §4 filters, ranking, sector-cluster flag, breadth
9. `execution/order.py` (MANUAL approval gate, idempotent order ids) + `execution/flatten.py` (15:15) + `journal/`
10. `review/nightly.py` — P&L after costs, R, expectancy, losing streak, re-entry tags, Brier, guard rejections → `reports/`
11. `main.py` — end-to-end day on FakeBroker with a recorded day of data; `notify/telegram.py` last
Not in stage 4: `broker/kis_client.py` (no account), `brain/daily_filter.py`, OpenDART fetcher, dashboard wiring.

### 3.3 Verify (stage 4 done when all hold)
- `python -m unittest discover tests` passes on Termux with stdlib only (no pip installs).
- Guard tests cover each rule in spec §6 with one pass and one reject case, plus missing-config → reject.
- A simulated full day on FakeBroker: orders only between 09:05 and 15:10, all positions flat after 15:15, every step in `journal/`, a report in `reports/`.
- A look-ahead test: feeding a future bar to the strategy raises an error.

## Review
- Phase A (2026-11-01): token auth on all /api routes of both Flask apps, bound to 127.0.0.1 by default, refuses to start without a token. Gemini key moved from the URL to the x-goog-api-key header. Broker and Gemini errors no longer echo response bodies. .gitignore patterns fixed. A random DASHBOARD_TOKEN was added to .env.
  Verified in .venv: no token or wrong token → 401, right token → 200, page 200, startup without token refused, no `?key=` left.
  Not verified: app.py /api/select_stocks with a real pandas (pandas does not build on Termux), the browser token prompt flow, and stage1 against the live Gemini API.
- Stage 4 progress (2026-11-05): steps 1–4 done (core/types, clock, ticks; risk/limits.toml + guard; execution/sizing; core/indicators). 75 unittest tests pass, stdlib only. Next: step 5 (broker/base + fake_broker).
  Guard behavior chosen within the spec: after drawdown/daily-loss stops, sells of held shares stay allowed so the 15:15 flat still works; the kill switch blocks every order, sells included (spec text). KRX tick table and costs 미검증. Holiday list goes in config/settings.toml at step 11.
- Stage 4 step 5 (2026-11-06): broker/base.py (Broker protocol) + broker/fake_broker.py. Fills at ask/bid when the limit is crossed, partial fills by displayed size, open buys hold cash, open sells hold shares, idempotent client ids, commission/tax truncated to won (미검증), daily bars hidden until closed. 96 tests pass.
- Stage 4 step 6 (2026-11-07): engine/state.py — Snapshot (numbers only, compact JSON), LookAheadError for any bar/quote after as_of, EquityTracker persists peak and day-start equity (restart-safe, corrupt file fails closed, reset_peak for the user). Quote gained day_open/high/low. 112 tests pass. Committed locally (f07c678, 6c7b92d), not pushed. Pushed 2026-11-07.
- Stage 4 step 7 (2026-11-07): strategy/schema.py (typed Signal, should_enter = spec §5) + strategy/breakout.py. Starting values approved 2026-11-08: quality = +1 breakout, +1 book (imbalance ≥ 0 and spread ≤ 30 bps), +1 Lead (cap 3); risk state 한도근접 at 75% of a loss limit; unknown breadth → 횡보; entry = last rounded up, stop = −2% rounded down. 130 tests pass.
- Stage 4 step 8 (2026-11-08): universe/screener.py — ADR ≥ 3.5%, 20-day traded value ≥ 10억, Lag and < 50 bars excluded, rank Lead then 1-month return, breadth now and 5 bars ago, sector cluster = ≥ 2 stocks in one sector turned Lead within 5 bars, save to data/screen/YYYY-MM-DD.json (gitignored). 139 tests pass.
- Stage 4 step 9 (2026-11-08): journal/writer.py (daily JSONL, fsync, torn-line tolerant); execution/order.py (guard → MANUAL approval with 5-min expiry and guard re-check → broker; AUTO refused on live; unknown order state blocks the symbol until resolved; buys journal entry_index 1st/2nd/3rd+, stop, initial risk); execution/flatten.py (15:15 cancel-all + sell-all, −2% hard stop exits, stops read from the journal). Approved 2026-11-08 (spec §7 updated): exit sells (flatten, hard stop) skip the MANUAL approval wait but still pass the guard. 158 tests pass.
- Stage 4 step 10 (2026-11-08): review/nightly.py — trades rebuilt from journal fills (re-entry = new trade, partial fills merged, open trades flagged), P&L after costs, R, expectancy, max losing streak, hit rate, Brier (p = quality/3, starting mapping), stats by entry index, guard-rejection tally, skipped signals, anomalies, leftover positions; Markdown report to reports/YYYY-MM-DD.md. 166 tests pass.
- Stage 4 step 11 (2026-11-08): config/settings.toml + core/config.py (fail closed; KRX holidays split confirmed / 미검증, both treated as closed); engine/day.py DayRunner (screen → quotes → approvals, stops, entries → 15:15 flatten → review); engine/sample.py made-up sample day; main.py (`simulate`, `--notify`, `--out`, `reset-peak`); notify/telegram.py (chunked, token never in errors); broker protocol gained get_fills; breakout entry now pays the ask so it can fill. Verify 3.3 all met: sample day buys only 09:05–15:10, flat after 15:15, every step journaled, report written; STOP mid-day blocks buys; MANUAL declined → no trades. 182 tests pass.
  Not verified: real Telegram send (asks first), real market data (sample day is made up), first-trading-day 10:00 open not handled.
- Gate 2 (2026-11-05): architecture v0.2 approved; spec §6 file name corrected from limits.yaml to limits.toml to match the architecture.
