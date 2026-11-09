# stock_bot — project guide for Claude

Korean-stock trading bot (KOSPI/KOSDAQ): code rules decide, a fixed risk guard checks every order, KIS (한국투자증권) executes. Today only a fake broker exists; no real orders are possible.

## Resume here
1. Read `tasks/todo.md` (stage status, decisions waiting for the user, review log) and `tasks/lessons.md` if present.
2. `git status` and `git log -5`; then continue the first unchecked item or ask the pending decision listed in todo.md.
3. Approved documents: `docs/spec.md` (rules), `docs/architecture.md` (modules), `docs/backtest.md` (stage 5 results).

## Commands
- Tests (stdlib only, no pip): `python3 -m unittest discover tests`
- Simulated day on the fake broker: `python3 main.py simulate` (`--notify` sends the report to Telegram — ask first; `--out DIR` keeps files)
- Backtest from cache: `python3 -m backtest.run --offline` (without `--offline` it refetches Yahoo daily bars, ~2.5 min)
- After a drawdown halt: `python3 main.py reset-peak`

## Layout
`core/` types, clock, ticks, indicators, config · `risk/` limits.toml + guard · `execution/` sizing, order service, exits · `broker/` protocol + fake broker · `engine/` snapshot, day runner, sample day · `strategy/` signal schema + breakout · `universe/` screener · `journal/` JSONL log · `review/` nightly report · `notify/` Telegram · `marketdata/` Yahoo daily bars · `backtest/` daily-bar backtest · `config/settings.toml`.
Runtime output goes to `var/` and `data/screen/` (gitignored). Legacy files (`trader.py`, `toss_api.py`, `agents/`, `app.py`, `dashboard/`, `stock_selector.py`) stay untouched until stage 6.

## Rules for this project
- Six stages, one user approval gate each; rule changes (spec, limits.toml) need approval.
- The guard is last and absolute; nothing may bypass it. Fail closed on bad config.
- No look-ahead: every snapshot/screen sees only bars closed before `as_of`.
- Money in `Decimal`, quantities `int`; stdlib only in the core.
- Secrets only in `.env` / `~/.config/telegram/bot.env`; never print or commit them.

## Working rules (adapted from the "Stop Ladder" in lennney/stop-that-shit, MIT)
1. Pin down the requested result and the guarantees to keep (spec, guard, tests) before changing code.
2. Start with what exists: project code, stdlib, the existing backtest harness. No new dependency without asking.
3. Add a mechanism only for a concrete gap (a real input, failure, or spec rule), not for hypothetical future needs.
4. Judge every safeguard by its effect: what it detects and what its rejection changes. Repair one that blocks legitimate work or hides a failure (example: the 11.25% drawdown "near limit" that stops trading forever, docs/backtest.md).
5. Verify with the project's tests, reuse evidence that is still valid, and stop when the result exists — do not repeat checks that cannot change the decision.
