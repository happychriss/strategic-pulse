# Change detector: historical test, model phase1-v0.4

Monthly from 2008-02 to 2026-10. Settings: unusual = 3-month change larger than 95% of the signal's own past changes; alarm = unusual moves in at least 2 layers. Events were fixed in `model/events.yaml` before the first run.

Approximation: ea_consumer_confidence, ea_economic_sentiment, ea_export_volume_yoy, ea_household_price_expectations, ea_import_volume_yoy, ea_industry_confidence, ea_unemployment_fears, ea_youth_unemployment, eu_asylum_applicants, eu_gas_imports_russia_share have no data vintages and use latest values from period end plus a publication lag (pseudo-real-time). All other signals use true vintages.

**8 of 11 events detected**; 21 alarm months outside any event window (63 alarm months in 226).

| Event | Month | First alarm | Lag (months) | First hint | Layers at alarm |
|---|---|---|---|---|---|
| Global financial crisis: Lehman Brothers collapse | 2008-09 | 2008-07 | -2 | 2008-06 | real_economy, societal_cohesion |
| Euro area sovereign debt crisis escalates (Italy, Spain) | 2011-07 | 2011-09 | 2 | 2011-06 | prices_policy, societal_cohesion |
| ECB takes the deposit rate negative; deflation fears | 2014-06 | none |  | none |  |
| Refugee influx into the EU peaks | 2015-09 | none |  | 2015-06 |  |
| Pandemic shock and lockdowns | 2020-03 | 2020-03 | 0 | 2020-03 | real_economy, societal_cohesion |
| Inflation surge begins (headline above 2% after years below) | 2021-07 | 2021-04 | -3 | 2021-04 | prices_policy, real_economy, resources_energy, societal_cohesion |
| Russia invades Ukraine; energy shock and gas cut-off | 2022-02 | 2021-11 | -3 | 2021-11 | international_integration, prices_policy, societal_cohesion |
| ECB raises rates for the first time in eleven years | 2022-07 | 2022-04 | -3 | 2022-04 | prices_policy, resources_energy, societal_cohesion |
| ECB's last hike; policy rate peaks | 2023-09 | 2023-06 | -3 | 2023-06 | prices_policy, resources_energy |
| ECB's first rate cut of the easing cycle | 2024-06 | none |  | none |  |
| War in the Middle East; new energy price shock | 2026-03 | 2026-04 | 1 | 2026-03 | prices_policy, resources_energy, societal_cohesion |

## Alarms outside event windows

2008-01, 2009-04, 2009-05, 2009-06, 2009-07, 2009-08, 2009-09, 2009-10, 2010-01, 2010-02, 2010-03, 2010-05, 2017-03, 2020-10, 2020-11, 2021-01, 2021-03, 2023-02, 2023-03, 2023-04, 2023-05

## Monthly levels

Level 2 = something is happening, 1 = unusual move in one layer, 0 = quiet.

```
2008  2 0 0 0 0 1 2 2 2 2 2 2
2009  2 2 2 2 2 2 2 2 2 2 1 1
2010  2 2 2 1 2 0 0 1 1 0 0 1
2011  1 1 1 0 0 1 1 0 2 1 0 0
2012  0 0 0 0 1 0 0 0 0 0 0 0
2013  0 0 0 0 0 0 0 0 1 0 0 0
2014  0 0 0 0 0 0 0 0 0 0 0 0
2015  0 1 1 0 0 1 1 0 0 0 0 0
2016  0 0 0 0 0 0 0 0 0 0 0 0
2017  1 0 2 1 1 0 1 1 0 0 0 0
2018  0 0 0 0 0 0 0 0 0 0 0 0
2019  0 0 0 0 0 0 0 0 0 0 0 0
2020  0 0 2 2 2 2 2 2 2 2 2 1
2021  2 1 2 2 2 2 2 2 2 2 2 2
2022  2 2 2 2 2 2 2 1 2 2 2 2
2023  2 2 2 2 2 2 0 0 0 1 1 1
2024  1 1 0 0 0 0 0 0 0 0 0 0
2025  0 0 0 0 0 0 0 0 0 0 0 0
2026  0 0 1 2 2 1 2 1 0 0
```
## Reading the result

- **Detected with useful timing:** the financial crisis (alarm two months before Lehman), the
  pandemic (same month), the 2021 inflation surge, the 2022 energy shock and tightening, the 2023
  rate peak and the 2026 Middle East shock (one month after).
- **Long continuous alarms reduce the value of a detection.** From 2020-03 to 2023-06 almost every
  month is level 2. The 2021, 2022 and 2023 events fall inside that run, so their negative lags
  partly reflect an alarm that was already on, not a fresh signal. A next version should report
  the onset of an alarm separately from its continuation.
- **Missed:** negative deposit rate 2014 (a 0.1-point step, not unusual in the data), refugee
  influx 2015 (asylum series starts 2014 and needs five years of history; only a one-layer hint)
  and the first cut in 2024 (a slow, well-telegraphed turn; this detector looks for unusual speed,
  not for a change of direction).
- **Alarms outside the event list** include 2009-10 (crisis aftermath, Greek crisis 2010),
  2020-10 to 2021-03 (second pandemic wave) and 2023-02 to 2023-05 (energy price collapse, bank
  turmoil in March 2023). Several look like real episodes missing from the list, but the list was
  fixed in advance, so they count as false alarms here. Extending the list now would tune the test.
- **Approximation:** 10 of 17 signals use pseudo-real-time values, so the test is somewhat
  optimistic for those layers.
