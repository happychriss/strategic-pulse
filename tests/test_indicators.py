from datetime import UTC, date, datetime

from srm.indicators import compound_4q, metric, monthly_mean, qoq_pct, step_monthly, yoy_pct


def monthly(values, start=(2023, 1)):
    y, m = start
    out = []
    for v in values:
        out.append((date(y, m, 1), f"{y}-{m:02d}", v))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_yoy_pct():
    pts = monthly([100.0] * 12 + [103.0])
    assert yoy_pct(pts) == [(date(2024, 1, 1), "2024-01", 3.0)]


def test_qoq_pct_quarterly():
    pts = [(date(2024, 1, 1), "2024-Q1", 200.0), (date(2024, 4, 1), "2024-Q2", 202.0)]
    assert qoq_pct(pts)[0][2] == 1.0


def test_compound_4q_needs_four_consecutive_quarters():
    q = [(date(2023, 3 * k + 1, 1), f"2023-Q{k + 1}", 1.0) for k in range(4)]
    out = compound_4q(q)
    assert len(out) == 1 and round(out[0][2], 2) == 4.06


def test_step_monthly_carries_rate_forward_to_cutoff():
    changes = [(date(2022, 7, 27), "2022-07-27", 0.0), (date(2022, 9, 14), "2022-09-14", 0.75)]
    out = step_monthly(changes, datetime(2022, 10, 15, tzinfo=UTC))
    assert [(lab, v) for _, lab, v in out] == [
        ("2022-07", 0.0),
        ("2022-08", 0.0),
        ("2022-09", 0.75),
        ("2022-10", 0.75),
    ]


def test_monthly_mean():
    pts = [(date(2024, 1, 2), "2024-01-02", 1.0), (date(2024, 1, 3), "2024-01-03", 3.0)]
    assert monthly_mean(pts) == [(date(2024, 1, 1), "2024-01", 2.0)]


def test_metric_change_needs_exact_reference_period():
    pts = monthly([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0])
    assert metric(pts, "level") == (8.0, "2023-07", None)
    assert metric(pts, "change_6m") == (7.0, "2023-07", "2023-01")
    assert metric(pts, "change_12m") is None
