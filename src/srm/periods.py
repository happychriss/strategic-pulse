"""Valid time: parse published period labels into half-open date ranges."""

from __future__ import annotations

import re
from datetime import date, timedelta

_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), "D"),
    (re.compile(r"^(\d{4})-(\d{2})$"), "M"),
    (re.compile(r"^(\d{4})-Q([1-4])$"), "Q"),
    (re.compile(r"^(\d{4})-S([12])$"), "S"),
    (re.compile(r"^(\d{4})$"), "A"),
]


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def parse_period(label: str) -> tuple[date, date, str]:
    """Return (start, end_exclusive, freq) for a period label such as 2026-Q2 or 2025-S2."""
    for pattern, freq in _PATTERNS:
        m = pattern.match(label)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        if freq == "D":
            start = date(g[0], g[1], g[2])
            return start, start + timedelta(days=1), freq
        if freq == "M":
            start = date(g[0], g[1], 1)
            return start, _add_months(start, 1), freq
        if freq == "Q":
            start = date(g[0], 3 * (g[1] - 1) + 1, 1)
            return start, _add_months(start, 3), freq
        if freq == "S":
            start = date(g[0], 6 * (g[1] - 1) + 1, 1)
            return start, _add_months(start, 6), freq
        return date(g[0], 1, 1), date(g[0] + 1, 1, 1), freq
    raise ValueError(f"unsupported period label: {label!r}")
