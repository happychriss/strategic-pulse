"""Change detector: "is something happening right now?"

    python -m srm.detect              # detection now, historical test, page data

Two lenses per signal, both measured against the signal's own history (data known at the time):
  speed      the latest 3-month change is larger than `sensitivity` of past 3-month changes
  direction  the 6-month change flips sign after a consistent run the other way (v0.5 onwards)
A layer is active when one of its signals shows either. An alarm ("something is happening")
needs at least `alarm_layers` active layers; a new alarm is one with no alarm in the previous
`onset_quiet_months` months. All settings live in the model version.

Signals with `knowledge: pseudo` have no data vintages: in historical tests their latest values
are treated as known from period end plus `lag_days`. This approximation is labelled in reports.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import psycopg
import yaml

from srm.indicators import _add_months, _by_start, indicator_series
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
    turn: bool | None = None  # direction change; None when the lens is off or not evaluable
    change_6m: float | None = None
    note: str = ""


@dataclass
class Detection:
    at: datetime
    level: int  # 0 quiet, 1 one active layer, 2 something is happening
    unusual_layers: list[str]  # active layers: unusual speed or direction change
    signals: list[SignalResult] = field(default_factory=list)
    onset: bool = False  # level 2 now and none in the previous onset_quiet_months


def config(label: str | None = None) -> dict:
    return read(f"versions/{label or current_label()}.yaml")["detector"]


def version_id(conn: psycopg.Connection, label: str | None) -> int:
    return conn.execute(
        "SELECT model_version_id FROM model.model_version WHERE label = %s",
        (label or current_label(),),
    ).fetchone()[0]


def quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def evaluate_points(
    points, at: datetime, window: int, sensitivity: float, min_history: int, r: SignalResult
):
    """Speed lens: is the latest change unusual against the signal's own past changes?"""
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


def evaluate_turn(points, turn: dict, r: SignalResult):
    """Direction lens: the 6-month change flips sign after a consistent run the other way, and the
    new move is larger than the median of the signal's own past 6-month moves."""
    if r.unusual is None:  # stale or too short: not evaluable either
        return
    w, look, consistency = turn["window_months"], turn["lookback_months"], turn["consistency"]
    idx = _by_start(points)
    d = [p[2] - idx[_add_months(p[0], -w)][2] for p in points if _add_months(p[0], -w) in idx]
    if len(d) < look + 12:
        return
    now = d[-1]
    r.change_6m = round(now, 4)
    prev = [v for v in d[-1 - look : -1] if v != 0]
    if now == 0 or len(prev) < 3:
        r.turn = False
        return
    share_pos = sum(v > 0 for v in prev) / len(prev)
    dominant = 1 if share_pos >= consistency else -1 if share_pos <= 1 - consistency else 0
    r.turn = (
        dominant != 0
        and (now > 0) != (dominant > 0)
        and abs(now) > quantile([abs(v) for v in d[:-1]], 0.5)
    )


def detect(
    conn: psycopg.Connection, at: datetime, label: str | None = None, now_cache: dict | None = None
) -> Detection:
    cfg = config(label)
    mv = version_id(conn, label)
    now_cache = now_cache if now_cache is not None else {}
    results = []
    for layer in cfg["layers"]:
        for sig in layer["signals"]:
            r = SignalResult(layer["key"], sig["indicator"], sig["knowledge"])
            if sig["knowledge"] == "vintage":
                pts = indicator_series(conn, sig["indicator"], at, mv)
            else:
                key = (mv, sig["indicator"])
                if key not in now_cache:
                    now_cache[key] = indicator_series(conn, sig["indicator"], datetime.now(UTC), mv)
                lag = timedelta(days=sig.get("lag_days", 0))
                pts = [
                    p
                    for p in now_cache[key]
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
            if "turn" in cfg:
                evaluate_turn(pts, cfg["turn"], r)
            results.append(r)
    active = sorted({r.layer for r in results if r.unusual or r.turn})
    level = 2 if len(active) >= cfg["alarm_layers"] else 1 if active else 0
    return Detection(at, level, active, results)


def mark_onsets(dets: list[Detection], quiet: int) -> None:
    for i, d in enumerate(dets):
        d.onset = d.level == 2 and all(p.level < 2 for p in dets[max(0, i - quiet) : i])


def backtest(
    conn, start=date(2008, 1, 1), end: date | None = None, label: str | None = None
) -> list[Detection]:
    end = end or datetime.now(UTC).date().replace(day=1)
    cache: dict = {}
    out, m = [], start
    while m <= end:
        at = min(datetime.combine(_add_months(m, 1), time(0), tzinfo=UTC), datetime.now(UTC))
        out.append(detect(conn, at, label, cache))
        m = _add_months(m, 1)
    mark_onsets(out, config(label).get("onset_quiet_months", 0))
    return out


def month_of(d: Detection) -> date:
    m = d.at - timedelta(seconds=1)
    return date(m.year, m.month, 1)


def score_events(
    dets: list[Detection], events: list[dict], before: int = 3, after: int = 6
) -> dict:
    """New alarm in the event window = detected; alarm already running = ongoing; else missed.
    False alarms are new alarms outside every event window."""
    months = {month_of(d): d for d in dets}
    rows, covered = [], set()
    for ev in events:
        y, mth = map(int, str(ev["month"]).split("-"))
        em = date(y, mth, 1)
        window = [_add_months(em, k) for k in range(-before, after + 1)]
        covered.update(window)
        onset = next((w for w in window if w in months and months[w].onset), None)
        alarm = next((w for w in window if w in months and months[w].level == 2), None)
        hit = onset or alarm
        rows.append(
            {
                "event": ev["label"],
                "month": em.strftime("%Y-%m"),
                "status": "new alarm" if onset else "alarm already running" if alarm else "missed",
                "alarm_month": hit.strftime("%Y-%m") if hit else None,
                "lag_months": None
                if hit is None
                else (hit.year - em.year) * 12 + (hit.month - em.month),
                "layers": months[hit].unusual_layers if hit else [],
            }
        )
    false_onsets = sorted(
        m.strftime("%Y-%m") for m, d in months.items() if d.onset and m not in covered
    )
    return {
        "events": rows,
        "false_alarms": false_onsets,
        "onsets": sum(d.onset for d in months.values()),
        "alarm_months": sum(d.level == 2 for d in months.values()),
        "months": len(months),
    }


def render_report(
    dets: list[Detection], scored: dict, cfg: dict, label: str, compare: dict | None = None
) -> str:
    pseudo = sorted(
        {
            s["indicator"]
            for layer in cfg["layers"]
            for s in layer["signals"]
            if s["knowledge"] == "pseudo"
        }
    )
    new = sum(r["status"] == "new alarm" for r in scored["events"])
    ongoing = sum(r["status"] == "alarm already running" for r in scored["events"])
    lines = [
        f"# Change detector: historical test, model {label}",
        "",
        (
            f"Monthly from {month_of(dets[0]):%Y-%m} to {month_of(dets[-1]):%Y-%m}. Speed lens: 3-month change "
            f"larger than {int(cfg['sensitivity'] * 100)}% of the signal's own past changes. "
            + (
                "Direction lens: 6-month change flips sign after a consistent run. "
                if "turn" in cfg
                else ""
            )
            + f"Alarm: at least {cfg['alarm_layers']} active layers; new alarm: none in the previous "
            f"{cfg.get('onset_quiet_months', 0)} months. Events fixed in `model/events.yaml` before the first run."
        ),
        "",
        (
            f"Approximation: {', '.join(pseudo)} have no data vintages and use latest values from period end plus a "
            "publication lag (pseudo-real-time). All other signals use true vintages."
        ),
        "",
        (
            f"**{new} of {len(scored['events'])} events with a new alarm**, {ongoing} with an alarm already running. "
            f"{len(scored['false_alarms'])} new alarms outside any event window ({scored['onsets']} new alarms; "
            f"{scored['alarm_months']} alarm months in {scored['months']})."
        ),
        "",
    ]
    if compare:
        lines += [
            "| Version | New alarm at event | Already running | Missed | New alarms outside events | Alarm months |",
            "|---|---|---|---|---|---|",
        ]
        for lab, sc in compare.items():
            st = [r["status"] for r in sc["events"]]
            lines.append(
                f"| {lab} | {st.count('new alarm')} | {st.count('alarm already running')} | {st.count('missed')} | "
                f"{len(sc['false_alarms'])} | {sc['alarm_months']} |"
            )
        lines.append("")
    lines += [
        "| Event | Month | Result | Alarm month | Lag (months) | Active layers |",
        "|---|---|---|---|---|---|",
    ]
    for r in scored["events"]:
        lines.append(
            f"| {r['event']} | {r['month']} | {r['status']} | {r['alarm_month'] or ''} | "
            f"{'' if r['lag_months'] is None else r['lag_months']} | {', '.join(r['layers'])} |"
        )
    lines += [
        "",
        "## New alarms outside event windows",
        "",
        ", ".join(scored["false_alarms"]) or "none",
        "",
        "## Monthly levels",
        "",
        "N = new alarm, 2 = alarm continuing, 1 = one active layer, 0 = quiet.",
        "",
        "```",
    ]
    by_year: dict[int, list[str]] = {}
    for d in dets:
        by_year.setdefault(month_of(d).year, []).append("N" if d.onset else str(d.level))
    lines += [f"{y}  {' '.join(v)}" for y, v in by_year.items()] + ["```", ""]
    return "\n".join(lines)


def page_payload(
    dets: list[Detection], scored: dict, structural_now: list, structural_hist: dict, label: str
) -> dict:
    """Everything the 'what is happening' view on the assessment page needs."""
    from srm.structural import asdict as s_asdict

    now = dets[-1]
    recent = dets[-4:]
    return {
        "model_version": label,
        "generated_utc": datetime.now(UTC).isoformat(),
        "now": {
            "month": month_of(now).strftime("%Y-%m"),
            "level": now.level,
            "onset": now.onset,
            "active_layers": now.unusual_layers,
            "signals": [asdict(s) for s in now.signals],
            "recent": [
                {"month": month_of(d).strftime("%Y-%m"), "level": d.level, "onset": d.onset}
                for d in recent
            ],
        },
        "timeline": [
            {
                "month": month_of(d).strftime("%Y-%m"),
                "level": d.level,
                "onset": d.onset,
                "layers": d.unusual_layers,
            }
            for d in dets
        ],
        "layers": [
            {"key": layer["key"], "label": layer["label"]} for layer in config(label)["layers"]
        ],
        "events": scored["events"],
        "false_alarms": scored["false_alarms"],
        "structural_now": [s_asdict(s) for s in structural_now],
        "structural_history": {
            y: [
                {
                    "key": s.key,
                    "axis": s.axis,
                    "unusual": s.unusual,
                    "turn": s.turn,
                    "toward": s.toward,
                }
                for s in rs
            ]
            for y, rs in structural_hist.items()
        },
    }


def run(conn, label: str | None = None) -> dict:
    """Backtest, score, structural layer; writes reports/detector/<label>.md and .json."""
    from srm.run_monthly import REPO
    from srm.structural import assess_structural, history

    label = label or current_label()
    events = yaml.safe_load((MODEL_DIR / "events.yaml").read_text())["events"]
    dets = backtest(conn, label=label)
    scored = score_events(dets, events)
    compare = {label: scored}
    if (
        label != "phase1-v0.4"
        and conn.execute("SELECT 1 FROM model.model_version WHERE label = 'phase1-v0.4'").fetchone()
    ):
        base = backtest(conn, label="phase1-v0.4")
        mark_onsets(
            base, config(label).get("onset_quiet_months", 3)
        )  # same new-alarm rule for both
        compare = {"phase1-v0.4 (speed only)": score_events(base, events), **compare}
    payload = page_payload(dets, scored, assess_structural(conn), history(conn, 2005), label)
    payload["indicator_labels"] = dict(
        conn.execute(
            "SELECT code, label FROM model.indicator WHERE model_version_id = %s",
            (version_id(conn, label),),
        ).fetchall()
    )
    payload["test_summary"] = {k: v for k, v in compare.items()}
    out = REPO / "reports" / "detector"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{label}.md").write_text(
        render_report(dets, scored, config(label), label, compare), encoding="utf-8"
    )
    (out / f"{label}.json").write_text(
        json.dumps(payload, indent=1, default=str) + "\n", encoding="utf-8"
    )
    return payload


def main(argv: list[str]) -> int:
    from srm.db import connect

    with connect() as conn:
        payload = run(conn)
    now = payload["now"]
    print(
        f"NOW {now['month']}: level {now['level']} new={now['onset']} active layers {now['active_layers']}"
    )
    for s in now["signals"]:
        flag = "UNUSUAL" if s["unusual"] else ("TURN" if s["turn"] else "")
        print(f"   {s['layer']:<26} {s['indicator']:<32} {s['latest_period']} {flag} {s['note']}")
    print(
        (MODEL_DIR.parent / "reports" / "detector" / f"{payload['model_version']}.md").read_text()
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
