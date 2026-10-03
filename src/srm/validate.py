"""Historical validation: did the assessed regime hold over the following 12 months?

    python -m srm.validate

For every month-end cutoff the regime position is computed with only the data known then
(as the system would have said it). The outcome is measured afterwards with today's data
(latest revised values). Outcome definitions are fixed here before looking at results:

Higher for longer realized (next 12 months)
    policy rate 12 months later >= max(2.0, policy rate at the cutoff)
    AND underlying inflation 12 months later > 2.5
Recession / disinflation realized (next 12 months)
    unemployment rises by >= 0.5 points at some month within the next 12 months
    AND headline inflation 12 months later < 2.0

A regime counts as called when its position is "supported" or "strongly supported".
Monthly cutoffs overlap heavily, so they are not independent observations: the number of
distinct episodes, not the number of months, limits what this test can show.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, time

from srm.assess import position
from srm.indicators import _add_months, current_version, indicator_series
from srm.regimes import evaluate

CALLED = {"supported", "strongly supported"}


def realized(series_now: dict[str, dict[date, float]], cutoff: date) -> dict:
    m0 = date(cutoff.year, cutoff.month, 1)
    m12 = _add_months(m0, 12)
    pol, core, head, une = (series_now[k] for k in ("policy", "core", "headline", "unemployment"))
    out = {
        "policy_now": pol.get(m0),
        "policy_12m": pol.get(m12),
        "core_12m": core.get(m12),
        "headline_12m": head.get(m12),
        "unemp_now": une.get(m0),
    }
    future_une = [une.get(_add_months(m0, k)) for k in range(1, 13)]
    out["unemp_max_rise"] = (
        max(v for v in future_une if v is not None) - out["unemp_now"]
        if out["unemp_now"] is not None and any(v is not None for v in future_une)
        else None
    )
    if None in (out["policy_now"], out["policy_12m"], out["core_12m"]):
        out["hfl"] = None
    else:
        out["hfl"] = out["policy_12m"] >= max(2.0, out["policy_now"]) and out["core_12m"] > 2.5
    if out["unemp_max_rise"] is None or out["headline_12m"] is None:
        out["rd"] = None
    else:
        out["rd"] = out["unemp_max_rise"] >= 0.5 and out["headline_12m"] < 2.0
    return out


def run(conn, start=date(2015, 1, 1), end=date(2025, 9, 1), model_version_id=None) -> list[dict]:
    mv = model_version_id or current_version(conn)
    now = datetime.now(UTC)
    by_month = {}
    for key, code in (
        ("policy", "ea_policy_rate"),
        ("core", "ea_hicp_core_yoy"),
        ("headline", "ea_hicp_headline_yoy"),
        ("unemployment", "ea_unemployment_rate"),
    ):
        by_month[key] = {p[0]: p[2] for p in indicator_series(conn, code, now, mv)}
    rows = []
    m = start
    while m <= end:
        at = datetime.combine(_add_months(m, 1), time(0), tzinfo=UTC)  # end of month m
        conds = evaluate(conn, at, mv)
        pos = {
            r: position([c for c in conds if c.regime == r])
            for r in ("higher_for_longer", "recession_disinflation")
        }
        rows.append(
            {
                "month": m,
                "hfl_called": pos["higher_for_longer"],
                "rd_called": pos["recession_disinflation"],
                **realized(by_month, m),
            }
        )
        m = _add_months(m, 1)
    return rows


def score(rows: list[dict], called_key: str, real_key: str) -> dict:
    rs = [r for r in rows if r[real_key] is not None]
    tp = sum(r[called_key] in CALLED and r[real_key] for r in rs)
    fp = sum(r[called_key] in CALLED and not r[real_key] for r in rs)
    fn = sum(r[called_key] not in CALLED and r[real_key] for r in rs)
    tn = sum(r[called_key] not in CALLED and not r[real_key] for r in rs)
    return {
        "months": len(rs),
        "hit": tp,
        "false_alarm": fp,
        "missed": fn,
        "correct_no": tn,
        "accuracy": round((tp + tn) / len(rs), 2) if rs else None,
    }


def main(argv: list[str]) -> int:
    from srm.db import connect

    with connect() as conn:
        rows = run(conn)
    for r in rows:
        print(
            f"{r['month']:%Y-%m}  HFL said {r['hfl_called']:<18} happened {r['hfl']!s:<5}  "
            f"RD said {r['rd_called']:<14} happened {r['rd']!s:<5}  "
            f"rate {r['policy_now']}->{r['policy_12m']}  core+12 {r['core_12m']}  head+12 {r['headline_12m']}  "
            f"unemp rise {None if r['unemp_max_rise'] is None else round(r['unemp_max_rise'], 2)}"
        )
    print("HFL", score(rows, "hfl_called", "hfl"))
    print("RD ", score(rows, "rd_called", "rd"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
