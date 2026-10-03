"""Yearly structural layer: trend changes across the nine axes, compared across member states.

For each indicator and member state the 5-year trend (least-squares slope) is compared with the
previous 5-year trend. A member state's change of trend is unusual when it is larger than the
`sensitivity` share of all member-state trend changes observed up to that year. Breadth = share
of member states with an unusual change in the dominant direction. A Europe-wide movement is
flagged when breadth is larger than the `sensitivity` share of breadth in earlier years and at
least three member states are involved. (An EU average moves far less than single countries,
so testing the average against the country distribution would almost never flag anything.)
The EU trend and a flip in its sign (direction change) are reported as description.

All values are latest releases; a year counts as known `lag_months` after it ends
(pseudo-real-time). There are no data vintages for these sources.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

import psycopg

from srm.detect import quantile
from srm.model_content import current_label, read

EU_MEMBERS = {
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "EL",
    "ES",
    "FI",
    "FR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
}


@dataclass
class StructuralResult:
    axis: str
    key: str
    label: str
    latest_year: int | None = None
    eu_value: float | None = None
    trend_now: float | None = None
    trend_before: float | None = None
    trend_change: float | None = None
    threshold: float | None = None
    unusual: bool | None = None
    turn: bool | None = None
    toward: str = ""  # "high pole" / "low pole" / ""
    breadth: float | None = None  # share of member states moving unusually the same way
    breadth_threshold: float | None = None
    countries: list[str] | None = None  # member states in the dominant unusual direction
    dispersion_ratio: float | None = None  # cross-country spread now / five years earlier
    members: int = 0
    note: str = ""


def config(label: str | None = None) -> dict:
    return read(f"versions/{label or current_label()}.yaml")["structural"]


def slope(values: list[float]) -> float:
    n = len(values)
    xs = range(n)
    mx, my = (n - 1) / 2, sum(values) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, values, strict=True)) / den


def load_panel(conn, family: str, match: dict) -> dict[str, dict[int, float]]:
    """region -> {year: value}, latest release, for series in `family` whose dims match."""
    rows = conn.execute(
        """SELECT s.region_code, s.dims, o.period_label, o.value
           FROM obs.series s JOIN obs.observation o USING (series_id)
           WHERE s.family = %s AND o.known_to IS NULL AND s.freq = 'A'""",
        (family,),
    ).fetchall()
    panel: dict[str, dict[int, float]] = {}
    for region, dims, period, value in rows:
        if region and all(str(dims.get(k)) == str(v) for k, v in match.items()):
            panel.setdefault(region, {})[int(period)] = float(value)
    return panel


def known_year(at: datetime, lag_months: int) -> int:
    """Latest year Y whose release date (Y+1)-01-01 plus lag_months is on or before `at`."""
    year = at.year - 1
    while True:
        months = (at.year - (year + 1)) * 12 + (at.month - 1)
        if months >= lag_months:
            return year
        year -= 1


def trend_at(series: dict[int, float], year: int, n: int) -> float | None:
    vals = [series.get(y) for y in range(year - n + 1, year + 1)]
    return None if any(v is None for v in vals) else slope(vals)


def assess_indicator(
    panel: dict[str, dict[int, float]], ind: dict, cfg: dict, at: datetime, aggregate: str
) -> StructuralResult:
    n = cfg["trend_years"]
    r = StructuralResult(ind["axis"], ind["key"], ind["label"])
    cutoff_year = known_year(at, ind.get("lag_months", 9))
    members = {
        g: {y: v for y, v in s.items() if y <= cutoff_year}
        for g, s in panel.items()
        if g in EU_MEMBERS
    }
    r.members = len(members)
    if ind.get("aggregate") == "mean_of_members" or aggregate not in panel:
        years = sorted({y for s in members.values() for y in s})
        agg = {
            y: statistics.fmean(s[y] for s in members.values() if y in s)
            for y in years
            if sum(y in s for s in members.values()) >= max(1, int(0.8 * len(members)))
        }
        r.note = "EU value = unweighted mean of member states"
    else:
        agg = {y: v for y, v in panel[aggregate].items() if y <= cutoff_year}
    if not agg:
        r.note = "no data known at this date"
        return r
    t = max(agg)
    r.latest_year, r.eu_value = t, round(agg[t], 4)
    now, before = trend_at(agg, t, n), trend_at(agg, t - n, n)
    if now is not None and before is not None:
        r.trend_now, r.trend_before = round(now, 4), round(before, 4)
        r.trend_change = round(now - before, 4)
    else:
        r.note = "EU series has gaps: no EU trend; member-state breadth still assessed"
    hist_changes, hist_slopes = [], []
    for s in members.values():
        for y in range(min(s, default=t) + 2 * n - 1, t + 1):
            a, b = trend_at(s, y, n), trend_at(s, y - n, n)
            if a is not None and b is not None:
                hist_changes.append(abs(a - b))
                hist_slopes.append(abs(a))
    if len(hist_changes) < 30:
        r.note = "too few member-state observations"
        return r
    r.threshold = round(quantile(hist_changes, cfg["sensitivity"]), 4)
    med = statistics.median(hist_slopes)
    if now is not None and before is not None:
        r.turn = (now > 0) != (before > 0) and abs(now) > med and abs(before) > med

    def breadth_at(year: int) -> tuple[float, int, list[str]]:
        up, down = [], []
        for g, s in members.items():
            a, b = trend_at(s, year, n), trend_at(s, year - n, n)
            if a is None or b is None or abs(a - b) <= r.threshold:
                continue
            (up if a > b else down).append(g)
        dominant, sign = (up, 1) if len(up) >= len(down) else (down, -1)
        return len(dominant) / max(1, len(members)), sign, sorted(dominant)

    r.breadth, sign, r.countries = breadth_at(t)
    r.breadth = round(r.breadth, 2)
    past = [breadth_at(y)[0] for y in range(t - 15, t)]
    past = [b for b in past if b is not None]
    if len(past) >= 8:
        r.breadth_threshold = round(quantile(past, cfg["sensitivity"]), 2)
        r.unusual = r.breadth > r.breadth_threshold and len(r.countries) >= 3
    else:
        r.note = (r.note + "; " if r.note else "") + "too few years to judge breadth"
    r.toward = "high pole" if sign * ind["high_pole_sign"] > 0 else "low pole"
    spread_now = [s[t] for s in members.values() if t in s]
    spread_before = [s[t - n] for s in members.values() if t - n in s]
    if len(spread_now) > 5 and len(spread_before) > 5 and statistics.pstdev(spread_before) > 0:
        r.dispersion_ratio = round(
            statistics.pstdev(spread_now) / statistics.pstdev(spread_before), 2
        )
    return r


def assess_structural(
    conn: psycopg.Connection, at: datetime | None = None, label: str | None = None
) -> list[StructuralResult]:
    cfg = config(label)
    at = at or datetime.now(UTC)
    out = []
    for ind in cfg["indicators"]:
        panel = load_panel(conn, ind["family"], ind["match"])
        out.append(assess_indicator(panel, ind, cfg, at, cfg["aggregate"]))
    return out


def history(
    conn: psycopg.Connection, start_year: int = 2005, label: str | None = None
) -> dict[int, list[StructuralResult]]:
    """Structural assessment as it would have looked at the end of each year (pseudo-real-time)."""
    cfg = config(label)
    panels = {
        ind["key"]: load_panel(conn, ind["family"], ind["match"]) for ind in cfg["indicators"]
    }
    out = {}
    for year in range(start_year, datetime.now(UTC).year + 1):
        at = min(datetime(year, 12, 31, 23, tzinfo=UTC), datetime.now(UTC))
        out[year] = [
            assess_indicator(panels[ind["key"]], ind, cfg, at, cfg["aggregate"])
            for ind in cfg["indicators"]
        ]
    return out


__all__ = ["StructuralResult", "asdict", "assess_structural", "date", "history", "slope"]
