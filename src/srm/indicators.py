"""Indicators computed as of a knowledge instant: only data knowable then is used."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import fmean

import psycopg

from srm.periods import _add_months, parse_period

Point = tuple[date, str, float]  # (period start, period label, value)


# ------------------------------------------------------------------ transforms (pure)
def _by_start(points: list[Point]) -> dict[date, Point]:
    return {p[0]: p for p in points}


def identity(points: list[Point], at: datetime | None = None) -> list[Point]:
    return points


def yoy_pct(points: list[Point], at: datetime | None = None) -> list[Point]:
    idx = _by_start(points)
    out = []
    for start, label, v in points:
        prev = idx.get(_add_months(start, -12))
        if prev and prev[2] != 0:
            out.append((start, label, round(100 * (v / prev[2] - 1), 4)))
    return out


def qoq_pct(points: list[Point], at: datetime | None = None) -> list[Point]:
    idx = _by_start(points)
    out = []
    for start, label, v in points:
        prev = idx.get(_add_months(start, -3))
        if prev and prev[2] != 0:
            out.append((start, label, round(100 * (v / prev[2] - 1), 4)))
    return out


def compound_4q(points: list[Point], at: datetime | None = None) -> list[Point]:
    """Quarter-on-quarter % changes compounded over the last four quarters."""
    idx = _by_start(points)
    out = []
    for start, label, _ in points:
        quarters = [idx.get(_add_months(start, -3 * k)) for k in range(4)]
        if all(quarters):
            prod = 1.0
            for q in quarters:
                prod *= 1 + q[2] / 100
            out.append((start, label, round(100 * (prod - 1), 4)))
    return out


def step_monthly(points: list[Point], at: datetime | None = None) -> list[Point]:
    """Series of change dates -> value in effect at each month end (or at `at`)."""
    if not points:
        return []
    changes = sorted(points)
    cutoff = at.date() if at else changes[-1][0]
    month = date(changes[0][0].year, changes[0][0].month, 1)
    out, i, current = [], 0, None
    while month <= cutoff:
        end = min(_add_months(month, 1), cutoff)
        while i < len(changes) and changes[i][0] < end:
            current = changes[i][2]
            i += 1
        if current is not None:
            out.append((month, month.strftime("%Y-%m"), current))
        month = _add_months(month, 1)
    return out


def monthly_mean(points: list[Point], at: datetime | None = None) -> list[Point]:
    groups: dict[date, list[float]] = defaultdict(list)
    for start, _, v in points:
        groups[date(start.year, start.month, 1)].append(v)
    return [(m, m.strftime("%Y-%m"), round(fmean(vs), 4)) for m, vs in sorted(groups.items())]


TRANSFORM_FUNCS = {
    "identity": identity,
    "yoy_pct": yoy_pct,
    "qoq_pct": qoq_pct,
    "compound_4q": compound_4q,
    "step_monthly": step_monthly,
    "monthly_mean": monthly_mean,
}


# ------------------------------------------------------------------ provenance
ObsKey = tuple  # (series_id, period Range, known_from): natural key of obs.observation


def _inputs_for(transform: str, start: date, raw: list[tuple[date, ObsKey]]) -> list[ObsKey]:
    """Raw observations that a derived point at `start` was computed from."""
    by_start = {s: k for s, k in raw}
    if transform == "identity":
        wanted = [start]
    elif transform == "yoy_pct":
        wanted = [start, _add_months(start, -12)]
    elif transform == "qoq_pct":
        wanted = [start, _add_months(start, -3)]
    elif transform == "compound_4q":
        wanted = [_add_months(start, -3 * k) for k in range(4)]
    elif transform == "monthly_mean":
        nxt = _add_months(start, 1)
        return [k for s, k in raw if start <= s < nxt]
    elif transform == "step_monthly":
        nxt = _add_months(start, 1)
        before = [k for s, k in raw if s < nxt]
        return before[-1:]
    else:
        raise ValueError(transform)
    return [by_start[w] for w in wanted if w in by_start]


# ------------------------------------------------------------------ database access
def current_version(conn: psycopg.Connection) -> int:
    """The model version named in model/current.yaml."""
    from srm.model_content import current_label

    label = current_label()
    row = conn.execute(
        "SELECT model_version_id FROM model.model_version WHERE label = %s", (label,)
    ).fetchone()
    if row is None:
        raise LookupError(f"model version {label!r} not loaded; run python -m srm.build")
    return row[0]


def indicator_series_with_inputs(
    conn: psycopg.Connection, code: str, at: datetime, model_version_id: int | None = None
) -> tuple[list[Point], dict[date, list[ObsKey]]]:
    """Indicator values knowable at `at`, plus the observations behind each value."""
    mv = model_version_id or current_version(conn)
    comps = conn.execute(
        """SELECT c.role, c.series_id, c.transform FROM model.indicator_component c
           JOIN model.indicator i USING (indicator_id)
           WHERE i.code = %s AND i.model_version_id = %s AND c.serves @> %s::timestamptz""",
        (code, mv, at),
    ).fetchall()
    by_role: dict[str, list[Point]] = {}
    inputs_by_role: dict[str, dict[date, list[ObsKey]]] = {}
    for role, series_id, transform in comps:
        rows = conn.execute(
            """SELECT lower(period), period_label, value, period, known_from FROM obs.as_of(%s, true)
               WHERE series_id = %s ORDER BY period""",
            (at, series_id),
        ).fetchall()
        pts = [(r[0], r[1], float(r[2])) for r in rows]
        raw = [(r[0], (series_id, r[3], r[4])) for r in rows]
        derived = TRANSFORM_FUNCS[transform](pts, at)
        by_role[role] = derived
        inputs_by_role[role] = {p[0]: _inputs_for(transform, p[0], raw) for p in derived}
    if {"minuend", "subtrahend"} <= set(by_role):
        sub = _by_start(by_role["subtrahend"])
        points = [(s, lab, round(v - sub[s][2], 4)) for s, lab, v in by_role["minuend"] if s in sub]
        inputs = {
            p[0]: inputs_by_role["minuend"][p[0]] + inputs_by_role["subtrahend"][p[0]]
            for p in points
        }
        return points, inputs
    points = list(by_role.get("value", []))
    inputs = dict(inputs_by_role.get("value", {}))
    # An extension appends only periods after the last value: fresher but non-vintage sources
    # can extend a vintage-safe series without replacing any of its history.
    if "extension" in by_role:
        last = points[-1][0] if points else None
        for p in by_role["extension"]:
            if last is None or p[0] > last:
                points.append(p)
                inputs[p[0]] = inputs_by_role["extension"][p[0]]
    return points, inputs


def indicator_series(
    conn: psycopg.Connection, code: str, at: datetime, model_version_id: int | None = None
) -> list[Point]:
    return indicator_series_with_inputs(conn, code, at, model_version_id)[0]


def metric(points: list[Point], name: str) -> tuple[float, str, str | None] | None:
    """(value, latest period label, reference period label) or None if not computable."""
    if not points:
        return None
    start, label, v = points[-1]
    if name == "level":
        return v, label, None
    months = {"change_3m": 3, "change_6m": 6, "change_12m": 12}[name]
    ref = _by_start(points).get(_add_months(start, -months))
    if ref is None:
        return None
    return round(v - ref[2], 4), label, ref[1]


def age_in_months(label: str, at: datetime) -> int:
    """Whole months between the end of the period and `at`; 0 for the current period."""
    _, end, _ = parse_period(label)
    return max(0, (at.year - end.year) * 12 + (at.month - end.month))
