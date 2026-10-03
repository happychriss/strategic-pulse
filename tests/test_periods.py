from datetime import date

import pytest

from srm.periods import parse_period


@pytest.mark.parametrize(
    "label,start,end,freq",
    [
        ("2026-09-16", date(2026, 9, 16), date(2026, 9, 17), "D"),
        ("2025-12", date(2025, 12, 1), date(2026, 1, 1), "M"),
        ("2026-Q2", date(2026, 4, 1), date(2026, 7, 1), "Q"),
        ("2025-Q4", date(2025, 10, 1), date(2026, 1, 1), "Q"),
        ("2025-S2", date(2025, 7, 1), date(2026, 1, 1), "S"),
        ("1995", date(1995, 1, 1), date(1996, 1, 1), "A"),
    ],
)
def test_parse_period(label, start, end, freq):
    assert parse_period(label) == (start, end, freq)


def test_unknown_label_is_rejected():
    with pytest.raises(ValueError):
        parse_period("2026-W05")
