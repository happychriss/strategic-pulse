from datetime import date

from srm.validate import realized, score


def series(start_value, months=14, step=0.0):
    return {date(2022 + (m // 12), m % 12 + 1, 1): start_value + step * m for m in range(months)}


def test_higher_for_longer_needs_high_rates_and_sticky_core():
    s = {
        "policy": series(2.0, step=0.2),
        "core": series(4.0),
        "headline": series(5.0),
        "unemployment": series(6.5),
    }
    r = realized(s, date(2022, 1, 1))
    assert r["hfl"] is True and r["rd"] is False


def test_easing_cycle_is_not_higher_for_longer():
    s = {
        "policy": series(3.0, step=-0.1),
        "core": series(2.4),
        "headline": series(1.8),
        "unemployment": series(6.5),
    }
    assert realized(s, date(2022, 1, 1))["hfl"] is False


def test_recession_needs_rising_unemployment_and_low_inflation():
    s = {
        "policy": series(0.0),
        "core": series(1.0),
        "headline": series(0.5),
        "unemployment": series(7.0, step=0.1),
    }
    assert realized(s, date(2022, 1, 1))["rd"] is True


def test_score_counts_hits_and_false_alarms():
    rows = [
        {"c": "supported", "r": True},
        {"c": "supported", "r": False},
        {"c": "mixed", "r": True},
        {"c": "not supported", "r": False},
        {"c": "supported", "r": None},
    ]
    assert score(rows, "c", "r") == {
        "months": 4,
        "hit": 1,
        "false_alarm": 1,
        "missed": 1,
        "correct_no": 1,
        "accuracy": 0.5,
    }
