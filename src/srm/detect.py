"""Change detector: "is something happening right now?"

    python -m srm.detect              # detection now, plus the historical test 2008-2026

No fixed levels. For every signal the latest 3-month change is compared with that signal's own
past 3-month changes (only data known at the time). A change is unusual when it is larger than
the `sensitivity` share of past changes. An alarm ("something is happening") needs unusual moves
in at least `alarm_layers` layers in the same month. Both settings live in the model version.

Signals with `knowledge: pseudo` have no data vintages: in historical tests their latest values
are treated as known from period end plus `lag_days`. This approximation is labelled in reports.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import psycopg
import yaml

from srm.indicators import _add_months, _by_start, current_version, indicator_series
from srm.model_content import MODEL_DIR, current_label, read
from srm.periods import parse_period


@dataclass
class SignalResult:
    layer: str
    indicator: str
    knowledge: str
    latest_period: str | None = None
    value: float | None = None
    change: float | None = None
    threshold: float | None = None
    history_months: int = 0
    unusual: bool | None = None  # None = not evaluable (too little history, or stale)
    note: str = ""


@dataclass
class Detection:
    at: datetime
    level: int  # 0 quiet, 1 unusual move in one layer, 2 something is happening
    unusual_layers: list[str]
    signals: list[SignalResult] = field(default_factory=list)


def config(label: str | None = None) -> dict:
    return read(f"versions/{label or current_label()}.yaml")["detector"]


def quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def evaluate_points(
    points, at: datetime, window: int, sensitivity: float, min_history: int, r: SignalResult
):
    """Fill r with the unusualness test of the latest change in `points`."""
    idx = _by_start(points)
    changes = [
        (p[0], p[1], p[2], p[2] - idx[_add_months(p[0], -window)][2])
        for p in points
        if _add_months(p[0], -window) in idx
    ]
    if not changes:
        r.note = "no change computable"
        return
    start, label, value, change = changes[-1]
    _, end, freq = parse_period(label)
    max_age = {"M": 4, "Q": 7}.get(freq, 4)
    age = (at.year - end.year) * 12 + (at.month - end.month)
    r.latest_period, r.value, r.change = label, round(value, 4), round(change, 4)
    hist = [abs(c[3]) for c in changes[:-1]]
    r.history_months = (start.year - changes[0][0].year) * 12 + (start.month - changes[0][0].month)
    if age > max_age:
        r.note = f"stale: latest period {label}"
        return
    if r.history_months < min_history or len(hist) < 12:
        r.note = "history too short"
        return
    r.threshold = round(quantile(hist, sensitivity), 4)
    r.unusual = abs(change) > r.threshold


def detect(
    conn: psycopg.Connection, at: datetime, label: str | None = None, now_cache: dict | None = None
) -> Detection:
    cfg = config(label)
    mv = (
        current_version(conn)
        if label is None
        else conn.execute(
            "SELECT model_version_id FROM model.model_version WHERE label = %s", (label,)
        ).fetchone()[0]
    )
    now_cache = now_cache if now_cache is not None else {}
    results = []
    for layer in cfg["layers"]:
        for sig in layer["signals"]:
            r = SignalResult(layer["key"], sig["indicator"], sig["knowledge"])
            if sig["knowledge"] == "vintage":
                pts = indicator_series(conn, sig["indicator"], at, mv)
            else:
                if sig["indicator"] not in now_cache:
                    now_cache[sig["indicator"]] = indicator_series(
                        conn, sig["indicator"], datetime.now(UTC), mv
                    )
                lag = timedelta(days=sig.get("lag_days", 0))
                pts = [
                    p
                    for p in now_cache[sig["indicator"]]
                    if datetime.combine(parse_period(p[1])[1], time(0), tzinfo=UTC) + lag <= at
                ]
            evaluate_points(
                pts,
                at,
                cfg["change_window_months"],
                cfg["sensitivity"],
                cfg["min_history_months"],
                r,
            )
            results.append(r)
    unusual_layers = sorted({r.layer for r in results if r.unusual})
    level = 2 if len(unusual_layers) >= cfg["alarm_layers"] else 1 if unusual_layers else 0
    return Detection(at, level, unusual_layers, results)


# ------------------------------------------------------------------ historical test
def backtest(
    conn, start=date(2008, 1, 1), end: date | None = None, label: str | None = None
) -> list[Detection]:
    end = end or datetime.now(UTC).date().replace(day=1)
    cache: dict = {}
    out, m = [], start
    while m <= end:
        at = datetime.combine(_add_months(m, 1), time(0), tzinfo=UTC)  # end of month m
        at = min(at, datetime.now(UTC))
        out.append(detect(conn, at, label, cache))
        m = _add_months(m, 1)
    return out


def score_events(
    dets: list[Detection], events: list[dict], before: int = 3, after: int = 6
) -> dict:
    months = {
        date(d.at.year, d.at.month, 1)
        if d.at.day > 1
        else _add_months(date(d.at.year, d.at.month, 1), -1): d
        for d in dets
    }
    rows, covered = [], set()
    for ev in events:
        y, mth = map(int, str(ev["month"]).split("-"))
        em = date(y, mth, 1)
        window = [_add_months(em, k) for k in range(-before, after + 1)]
        covered.update(window)
        alarm = next((w for w in window if w in months and months[w].level == 2), None)
        hint = next((w for w in window if w in months and months[w].level >= 1), None)
        lag = None if alarm is None else (alarm.year - em.year) * 12 + (alarm.month - em.month)
        rows.append(
            {
                "event": ev["label"],
                "month": em.strftime("%Y-%m"),
                "alarm_month": alarm and alarm.strftime("%Y-%m"),
                "lag_months": lag,
                "first_hint": hint and hint.strftime("%Y-%m"),
                "layers": months[alarm].unusual_layers if alarm else [],
            }
        )
    false_alarms = sorted(
        m.strftime("%Y-%m") for m, d in months.items() if d.level == 2 and m not in covered
    )
    return {
        "events": rows,
        "false_alarms": false_alarms,
        "alarm_months": sum(d.level == 2 for d in months.values()),
        "months": len(months),
    }


def render_report(dets: list[Detection], scored: dict, cfg: dict, label: str) -> str:
    pseudo = sorted(
        {
            s["indicator"]
            for layer in cfg["layers"]
            for s in layer["signals"]
            if s["knowledge"] == "pseudo"
        }
    )
    det = sum(r["alarm_month"] is not None for r in scored["events"])
    lines = [
        f"# Change detector: historical test, model {label}",
        "",
        (
            f"Monthly from {dets[0].at:%Y-%m} to {dets[-1].at:%Y-%m}. Settings: unusual = 3-month change larger than "
            f"{int(cfg['sensitivity'] * 100)}% of the signal's own past changes; alarm = unusual moves in at least "
            f"{cfg['alarm_layers']} layers. Events were fixed in `model/events.yaml` before the first run."
        ),
        "",
        (
            f"Approximation: {', '.join(pseudo)} have no data vintages and use latest values from period end plus a "
            "publication lag (pseudo-real-time). All other signals use true vintages."
        ),
        "",
        (
            f"**{det} of {len(scored['events'])} events detected**; {len(scored['false_alarms'])} alarm months outside any "
            f"event window ({scored['alarm_months']} alarm months in {scored['months']})."
        ),
        "",
        "| Event | Month | First alarm | Lag (months) | First hint | Layers at alarm |",
        "|---|---|---|---|---|---|",
    ]
    for r in scored["events"]:
        lines.append(
            f"| {r['event']} | {r['month']} | {r['alarm_month'] or 'none'} | "
            f"{'' if r['lag_months'] is None else r['lag_months']} | {r['first_hint'] or 'none'} | "
            f"{', '.join(r['layers'])} |"
        )
    lines += [
        "",
        "## Alarms outside event windows",
        "",
        ", ".join(scored["false_alarms"]) or "none",
        "",
        "## Monthly levels",
        "",
        "Level 2 = something is happening, 1 = unusual move in one layer, 0 = quiet.",
        "",
        "```",
    ]
    by_year: dict[int, list[str]] = {}
    for d in dets:
        m = d.at - timedelta(seconds=1)
        by_year.setdefault(m.year, []).append(str(d.level))
    lines += [f"{y}  {' '.join(v)}" for y, v in by_year.items()]
    lines += ["```", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    from srm.db import connect
    from srm.run_monthly import REPO

    label = current_label()
    cfg = config(label)
    events = yaml.safe_load((MODEL_DIR / "events.yaml").read_text())["events"]
    with connect() as conn:
        now = detect(conn, datetime.now(UTC))
        dets = backtest(conn)
    scored = score_events(dets, events)
    out = REPO / "reports" / "detector"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{label}.md").write_text(render_report(dets, scored, cfg, label), encoding="utf-8")
    print(f"NOW level {now.level}: unusual layers {now.unusual_layers}")
    for s in now.signals:
        print(
            f"   {s.layer:<26} {s.indicator:<32} {s.latest_period} change={s.change} thr={s.threshold} "
            f"unusual={s.unusual} {s.note}"
        )
    print(render_report(dets, scored, cfg, label))
    return 0


__all__ = ["Detection", "SignalResult", "asdict", "backtest", "detect", "score_events"]

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
