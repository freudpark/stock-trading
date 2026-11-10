# Backtest v1 (2026-11-08)

**Verdict: v1 fails go-live gate 1 (positive expectancy after costs). Do not start paper trading with v1 as is.**

## Setup
- Data: Yahoo daily bars (split-adjusted, cached in `var/cache/yahoo/`), 20 liquid KOSPI200/KOSDAQ150 names (`backtest/run.py`), test period 2024-02-20 – 2026-11-06 (after a 71-bar warm-up).
- Rules: spec v1.1 — screener (Lead/Mediocre, ADR ≥ 3.5%, value ≥ 10억), breadth regime, K = 0.5 breakout, −2% stop, exit at the close (stand-in for 15:15), 1% risk, 20% weight, 5 positions, daily loss and drawdown rules, costs (commission 0.015%/side, sell tax 0.20%, both 미검증) plus 1 tick slippage on entry and exit.
- Daily bars hide the order of the high and the low, so two stop rules: **pessimistic** (any touch of the stop counts) and **path** (up day: open→low→high→close; down day: open→high→low→close).
- Order-book quality point is unknown in daily bars: **lead-only** (never awarded) and **book** (always awarded).
- Not modelled: earnings block, VI/halts, intraday timing of entries.
- Reproduce: `python3 -m backtest.run --offline` (needs the cache; without `--offline` it refetches).

## Results (start 10,000,000원)
| Variant | Trades | Expectancy | Hit rate | Max losing streak | Return | Max DD |
|---|---|---|---|---|---|---|
| pessimistic / lead-only | 31 | −1.03R | 6.5% | 24 | −11.9% | 11.9% |
| pessimistic / book | 31 | −1.02R | 6.5% | 22 | −11.7% | 11.7% |
| path / lead-only | 285 | −0.06R | 37.2% | 13 | −7.3% | 11.4% |
| path / book | 213 | −0.11R | 35.7% | 13 | −8.8% | 11.8% |

With the live risk rules every variant stopped trading in 2024: once drawdown reached 11.25% (the "near limit" at 75% of the 15% halt) no new entry was allowed, and with no trades the account can never recover. **The 11.25% block is a permanent stop in practice, earlier than the 15% halt.**

Research mode (drawdown stops off, to see the edge over the whole period; not a live setting):

| Variant | Trades | Expectancy | Hit rate | Max losing streak | Return | Max DD |
|---|---|---|---|---|---|---|
| path / lead-only | 1,237 | −0.07R | 34.8% | 17 | −32.3% | 35.3% |
| path / book | 1,639 | −0.09R | 35.0% | 19 | −42.6% | 44.5% |
| pessimistic / lead-only | 774 | −0.97R | 6.3% | 75 | −93.1% | 93.1% |

Path / lead-only per year: 2024 −0.11R (436 trades), 2025 −0.06R (474), 2026 −0.05R (327). Negative every year.

Cost split (path / lead-only, research): result before fees and tax +0.04R per trade (after slippage), fees and tax −0.11R per trade, net −0.07R. The sell tax alone is about 0.1R because 1R is only a 2% move.

## Caveats
- Survivorship bias: the 20 names were picked in 2026 with hindsight, so real results would likely be worse.
- Daily-bar approximation; the truth is between the pessimistic and path rows, likely close to path.
- Tax and commission rates are 미검증; a lower sell tax would not turn the result positive (costs would need to fall by more than 60%).

## Options (user decision)
1. Stop v1. Test the deferred v2 candidate (EMA-confluence pullback, wider structure stop) with the same harness. Needs a spec change (it holds overnight).
2. Tune v1 (K, stop width, fewer but higher-quality trades) — risk of overfitting; any change must be validated on a period not used for tuning.
3. Fix the permanent-stop issue regardless: decide what should happen after the 11.25% block (e.g. halt + user reset, as for 15%).

## Update 2026-11-10: near-limit changed to 축소 (reduced risk)
Spec §6 now keeps trading past 11.25% drawdown at 0.2% risk per trade (about half size) instead of blocking entries forever. Rerun from cache (`python3 -m backtest.run --offline`, var/backtest/2026-11-11/summary.json):

| variant | trades | exp R | hit | streak | return % | max DD % | halted |
|---|---|---|---|---|---|---|---|
| pessimistic/lead-only | 54 | −0.954 | 0.093 | 24 | −15.01 | 15.01 | 2024-03-14 |
| pessimistic/book | 61 | −0.908 | 0.115 | 22 | −15.51 | 15.51 | 2024-03-14 |
| path/lead-only | 364 | −0.098 | 0.343 | 13 | −11.24 | 15.15 | 2024-10-18 |
| path/book | 433 | −0.081 | 0.360 | 13 | −12.25 | 15.10 | 2024-09-30 |

The permanent stop is gone: trading now runs on to the 15% halt, which waits for the user's reset (`python3 main.py reset-peak`), as designed. Research-mode numbers are unchanged. v1 still has negative expectancy, so gate 1 is still failed.
