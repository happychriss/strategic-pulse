# Change detector: historical test, model phase1-v0.5

Monthly from 2008-01 to 2026-10. Speed lens: 3-month change larger than 95% of the signal's own past changes. Direction lens: 6-month change flips sign after a consistent run. Alarm: at least 2 active layers; new alarm: none in the previous 3 months. Events fixed in `model/events.yaml` before the first run.

Approximation: ea_consumer_confidence, ea_economic_sentiment, ea_export_volume_yoy, ea_household_price_expectations, ea_import_volume_yoy, ea_industry_confidence, ea_unemployment_fears, ea_youth_unemployment, eu_asylum_applicants, eu_gas_imports_russia_share have no data vintages and use latest values from period end plus a publication lag (pseudo-real-time). All other signals use true vintages.

**5 of 11 events with a new alarm**, 4 with an alarm already running. 7 new alarms outside any event window (12 new alarms; 80 alarm months in 226).

| Version | New alarm at event | Already running | Missed | New alarms outside events | Alarm months |
|---|---|---|---|---|---|
| phase1-v0.4 (speed only) | 4 | 4 | 3 | 2 | 63 |
| phase1-v0.5 | 5 | 4 | 2 | 7 | 80 |

| Event | Month | Result | Alarm month | Lag (months) | Active layers |
|---|---|---|---|---|---|
| Global financial crisis: Lehman Brothers collapse | 2008-09 | new alarm | 2008-07 | -2 | real_economy, societal_cohesion |
| Euro area sovereign debt crisis escalates (Italy, Spain) | 2011-07 | new alarm | 2011-08 | 1 | real_economy, societal_cohesion |
| ECB takes the deposit rate negative; deflation fears | 2014-06 | missed |  |  |  |
| Refugee influx into the EU peaks | 2015-09 | missed |  |  |  |
| Pandemic shock and lockdowns | 2020-03 | new alarm | 2020-03 | 0 | real_economy, societal_cohesion |
| Inflation surge begins (headline above 2% after years below) | 2021-07 | alarm already running | 2021-04 | -3 | prices_policy, real_economy, resources_energy, societal_cohesion |
| Russia invades Ukraine; energy shock and gas cut-off | 2022-02 | alarm already running | 2021-11 | -3 | international_integration, prices_policy, societal_cohesion |
| ECB raises rates for the first time in eleven years | 2022-07 | alarm already running | 2022-04 | -3 | prices_policy, real_economy, resources_energy, societal_cohesion |
| ECB's last hike; policy rate peaks | 2023-09 | alarm already running | 2023-06 | -3 | prices_policy, resources_energy |
| ECB's first rate cut of the easing cycle | 2024-06 | new alarm | 2024-06 | 0 | international_integration, prices_policy, resources_energy |
| War in the Middle East; new energy price shock | 2026-03 | new alarm | 2026-03 | 0 | international_integration, prices_policy, resources_energy |

## New alarms outside event windows

2008-01, 2011-01, 2012-05, 2017-03, 2017-08, 2018-07, 2025-10

## Monthly levels

N = new alarm, 2 = alarm continuing, 1 = one active layer, 0 = quiet.

```
2008  N 0 0 0 0 1 N 2 2 2 2 2
2009  2 2 2 2 2 2 2 2 2 2 1 2
2010  2 2 2 1 2 1 0 1 1 0 1 1
2011  N 2 1 0 0 1 1 N 2 1 0 2
2012  1 1 0 1 N 1 1 0 0 0 0 0
2013  1 0 1 1 0 0 0 0 1 0 0 0
2014  0 0 0 0 0 0 0 0 0 0 0 0
2015  0 1 1 0 0 1 1 1 1 0 0 1
2016  0 0 0 0 0 0 0 0 0 1 1 0
2017  1 1 N 1 1 0 1 N 2 0 0 0
2018  0 0 0 0 1 1 N 2 1 0 0 0
2019  0 0 0 1 0 0 0 0 0 0 0 1
2020  0 0 N 2 2 2 2 2 2 2 2 2
2021  2 2 2 2 2 2 2 2 2 2 2 2
2022  2 2 2 2 2 2 2 1 2 2 2 2
2023  2 2 2 2 2 2 1 0 1 1 1 1
2024  1 1 1 1 1 N 2 1 0 0 0 0
2025  0 0 0 1 1 0 0 0 0 N 0 0
2026  0 0 N 2 2 2 2 1 1 1
```
## Reading the result

- **Same new-alarm rule for both versions.** v0.4 (speed only) and v0.5 (speed plus direction)
  are scored identically: a new alarm needs three quiet months before it.
- **The direction lens is a trade-off, not a clear gain.** It catches the first rate cut in June
  2024 (same month) and turns one miss into a detection, but adds five new alarms outside the
  event list (2011-01, 2012-05, 2017-03, 2017-08, 2018-07, 2025-10 among them) and lengthens alarm
  periods (80 alarm months instead of 63).
- **Option for v0.6, to be decided rather than tuned:** treat a direction change as a one-layer
  hint that is shown but does not count toward an alarm on its own.
- **Still missed:** the 2014 negative rate (a small step) and the 2015 refugee influx (asylum
  series too short for a five-year history).
- **Yearly structural layer:** flags Europe-wide movements in government debt 2011-2014 (euro
  crisis), old-age dependency 2015-2017 (ageing accelerating), government expenditure 2015-2018 and
  2022, and fertility in 2026 (decline accelerating in several states). Governance never moves
  Europe-wide; its deteriorations are country-specific.
