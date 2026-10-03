"""Knowledge time: when a value became knowable, and collapsing vintages into intervals.

Every rule errs late. A backtest may miss a value that was in fact public slightly
earlier, but it can never see a value before it could have been published.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

PRECISION = {
    "source_vintage_log": "minute",
    "revdate_dimension": "day",
    "edition_dimension": "month",
    "release_rule": "release_rule",
    "ingestion": "retrieval",
}
# Rules where every vintage republishes the full series: a period missing from a later
# vintage is no longer published at that vintage.
DENSE_RULES = {"revdate_dimension", "edition_dimension"}


def revdate_time(revdate: str) -> datetime:
    """Eurostat revision date: knowable from the end of that day (UTC)."""
    d = date.fromisoformat(revdate)
    return datetime.combine(d + timedelta(days=1), time(0), tzinfo=UTC)


def edition_time(edition: str) -> datetime:
    """OECD edition YYYYMM: knowable from the first day of the following month (UTC)."""
    y, m = int(edition[:4]), int(edition[4:6])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return datetime(y, m, 1, tzinfo=UTC)


def release_time(period_end_exclusive: date, lag_days: int) -> datetime:
    """Unrevised data: knowable once the period is over, plus a release lag."""
    return datetime.combine(period_end_exclusive, time(0), tzinfo=UTC) + timedelta(days=lag_days)


def parse_lag_days(lag: str) -> int:
    if not (lag.startswith("P") and lag.endswith("D")):
        raise ValueError(f"release_lag must look like P1D, got {lag!r}")
    return int(lag[1:-1])


@dataclass(frozen=True)
class Event:
    """At instant t the source published `value` for a period, or withdrew it (value None)."""

    t: datetime
    value: Decimal | None
    status: str | None = None
    attrs: tuple[tuple[str, str], ...] | None = None
    snapshot_id: str | None = None

    def same_content(self, other: Event) -> bool:
        return (self.value, self.status, self.attrs) == (other.value, other.status, other.attrs)


@dataclass(frozen=True)
class Interval:
    known_from: datetime
    known_to: datetime | None
    value: Decimal
    status: str | None
    attrs: tuple[tuple[str, str], ...] | None
    snapshot_id: str | None


def collapse(
    events: Iterable[Event], vintage_times: Iterable[datetime] | None = None
) -> list[Interval]:
    """Turn publication events for one series-period into non-overlapping knowledge intervals.

    Consecutive identical publications merge into one interval. A withdrawal, or (for dense
    vintage tables) absence from a later vintage, closes the open interval.
    """
    by_time: dict[datetime, Event] = {}
    # Stable sort: at one instant a publication beats a withdrawal (a replacement closes the
    # previous value), and among publications the earliest snapshot wins.
    for ev in sorted(events, key=lambda e: (e.t, e.value is None)):
        by_time.setdefault(ev.t, ev)

    if vintage_times is not None:
        timeline = [by_time.get(t, Event(t=t, value=None)) for t in sorted(set(vintage_times))]
        # Before the first appearance a missing period is simply not yet published.
        first = next((i for i, e in enumerate(timeline) if e.value is not None), None)
        timeline = [] if first is None else timeline[first:]
    else:
        timeline = [by_time[t] for t in sorted(by_time)]

    out: list[Interval] = []
    current: Event | None = None
    for ev in timeline:
        if current is not None and ev.value is not None and ev.same_content(current):
            continue
        if current is not None:
            out.append(_interval(current, ev.t))
            current = None
        if ev.value is not None:
            current = ev
    if current is not None:
        out.append(_interval(current, None))
    return out


def _interval(ev: Event, end: datetime | None) -> Interval:
    assert ev.value is not None
    return Interval(ev.t, end, ev.value, ev.status, ev.attrs, ev.snapshot_id)
