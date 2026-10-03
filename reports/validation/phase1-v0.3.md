# Historical validation, model phase1-v0.3

Generated with `python -m srm.validate` on 2026-10-03. Each month-end from 2015-01 to 2025-09:
regime position computed with data known then; outcome measured 12 months later with today's
data. Outcome definitions are fixed in `src/srm/validate.py` (written before the results).

| Regime | Months | Called and happened | False alarm | Missed | Correctly not called | Accuracy |
|---|---|---|---|---|---|---|
| Higher for longer | 129 | 21 | 72 | 0 | 36 | 0.44 |
| Recession / disinflation | 129 | 0 | 8 | 12 | 109 | 0.84 |

Base rate: higher for longer happened in 21 of 129 months, so always answering "no" would score
0.84. The system currently adds value only in the 2022-23 episode.

## The four cutoffs on the assessment page

| Cutoff | Said | Next 12 months | Verdict |
|---|---|---|---|
| 2019-12 | Higher for longer mixed; recession not supported | Rates flat at -0.5%, core 0.2%, unemployment up 1.2 points (pandemic) | Higher for longer right; recession missed (exogenous shock) |
| 2021-12 | Higher for longer strongly supported | Deposit rate -0.5% to 2.0%, core 5.2% | Right |
| 2022-12 | Higher for longer strongly supported | Deposit rate 2.0% to 4.0%, core 3.4% | Right |
| 2024-12 | Higher for longer supported, increasing | Deposit rate 3.0% to 2.0%, core 2.3% | Wrong: easing followed |

## Findings

1. **False alarms 2015-2019.** Momentum conditions alone (core not falling, yields rising) yield
   net +0.5 and "supported" while rates were negative and core near 1%. The level conditions
   (core above target, policy at or above neutral) should be necessary, not additive.
2. **Late at turning points.** Easing began in June 2024; the system still said supported in
   early 2024 and again in early 2025. Conditions describe the present state; the name promises
   persistence ("for longer"), which nothing in v0.3 tests.
3. **Early in 2021.** Supported from April 2021, the tightening came 12-18 months later; with a
   12-month horizon those months count as false alarms. Results depend on the horizon.
4. **Recession is detected after the fact.** Unemployment and GDP are coincident indicators:
   the 2020 recession was not called beforehand, and the label stayed on into early 2021.
5. **Sample size.** Monthly cutoffs overlap; there are about three distinct episodes
   (2015-19 low inflation, 2022-23 tightening, 2024-25 easing). Any fix designed on this history
   must be checked on later months or another region before it is trusted.
