from datetime import UTC, datetime

from srm.structural import EU_MEMBERS, assess_indicator, known_year, slope

CFG = {"sensitivity": 0.95, "trend_years": 5}
IND = {"axis": "a", "key": "k", "label": "x", "high_pole_sign": 1, "lag_months": 6}


def test_slope_and_publication_lag():
    assert slope([1, 2, 3, 4, 5]) == 1
    assert known_year(datetime(2026, 10, 3, tzinfo=UTC), 6) == 2025
    assert known_year(datetime(2026, 3, 1, tzinfo=UTC), 6) == 2024
    assert known_year(datetime(2026, 10, 3, tzinfo=UTC), 15) == 2024


def panel(jump_states: set[str], jump_year: int = 2024):
    out = {}
    for i, g in enumerate(sorted(EU_MEMBERS)):
        series = {}
        for y in range(1995, 2026):
            v = 50 + 0.3 * (y - 1995) + (0.4 if (i + y) % 3 == 0 else 0.0)
            if g in jump_states and y >= jump_year:  # the movement starts in the assessed year
                v += 6.0 * (y - jump_year + 1)
            series[y] = v
        out[g] = series
    out["EU27_2020"] = {
        y: sum(s[y] for k, s in out.items() if k in EU_MEMBERS) / 27 for y in range(1995, 2026)
    }
    return out


def test_europe_wide_movement_is_flagged_only_when_many_states_move():
    at = datetime(2025, 12, 31, tzinfo=UTC)
    quiet = assess_indicator(panel(set()), IND, CFG, at, "EU27_2020")
    assert quiet.unusual is False
    broad = assess_indicator(
        panel({"DE", "FR", "IT", "ES", "PL", "NL", "BE"}), IND, CFG, at, "EU27_2020"
    )
    assert broad.unusual is True and broad.toward == "high pole" and len(broad.countries) >= 3
