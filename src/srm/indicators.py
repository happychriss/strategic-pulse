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


# ------------------------------------------------------------------ database access
def current_version(conn: psycopg.Connection) -> int:
    """The model version named in model/model.yaml, the definitions on disk."""
    from srm.model_content import read

    label = read("model.yaml")["model_version"]["label"]
    row = conn.execute(
        "SELECT model_version_id FROM model.model_version WHERE label = %s", (label,)
    ).fetchone()
    if row is None:
        raise LookupError(f"model version {label!r} not loaded; run python -m srm.build")
    return row[0]


def indicator_series(
    conn: psycopg.Connection, code: str, at: datetime, model_version_id: int | None = None
) -> list[Point]:
    mv = model_version_id or current_version(conn)
    comps = conn.execute(
        """SELECT c.role, c.series_id, c.transform FROM model.indicator_component c
           JOIN model.indicator i USING (indicator_id)
           WHERE i.code = %s AND i.model_version_id = %s AND c.serves @> %s::timestamptz""",
        (code, mv, at),
    ).fetchall()
    by_role: dict[str, list[Point]] = {}
    for role, series_id, transform in comps:
        rows = conn.execute(
            """SELECT lower(period), period_label, value FROM obs.as_of(%s, true)
               WHERE series_id = %s ORDER BY period""",
            (at, series_id),
        ).fetchall()
        pts = [(r[0], r[1], float(r[2])) for r in rows]
        by_role[role] = TRANSFORM_FUNCS[transform](pts, at)
    if {"minuend", "subtrahend"} <= set(by_role):
        sub = _by_start(by_role["subtrahend"])
        return [(s, lab, round(v - sub[s][2], 4)) for s, lab, v in by_role["minuend"] if s in sub]
    return by_role.get("value", [])


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
    _, end, _ = parse_period(label)
    return (at.year - end.year) * 12 + (at.month - end.month)
