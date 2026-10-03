from datetime import date

from srm.dashboard import (
    LAYERS_DE,
    SIGNALS_DE,
    STRUCTURAL_DE,
    breadth_sentence,
    heat_opacity,
    level_sentence,
    months_of,
    move_ranks,
    move_sentence,
    num,
    period_de,
    record,
    render,
    signal_stats,
    top_levels,
    top_moves,
)
from srm.detect import config
from srm.structural import config as structural_config


def monthly(values, start=(2000, 1)):
    y, m, out = *start, []
    for v in values:
        out.append((date(y, m, 1), f"{y}-{m:02d}", float(v)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_german_number_format():
    assert num(3.8) == "3,8"
    assert num(-16.5) == "−16,5"
    assert num(1.0, 1, True) == "+1,0"
    assert num(None) == "–"


def test_periods_read_the_german_way():
    assert period_de("2026-09") == "09/2026"
    assert period_de("2026-Q2") == "Q2/2026"
    assert months_of("2008-Q3") == ["2008-07", "2008-08", "2008-09"]
    assert months_of("2008-07") == ["2008-07"]


def test_every_signal_layer_and_axis_of_the_current_model_has_a_german_name():
    cfg = config()
    assert {layer["key"] for layer in cfg["layers"]} <= set(LAYERS_DE)
    sigs = {s["indicator"] for layer in cfg["layers"] for s in layer["signals"]}
    assert sigs <= set(SIGNALS_DE)
    assert {i["key"] for i in structural_config()["indicators"]} <= set(STRUCTURAL_DE)


def test_latest_value_and_move_are_ranked_against_the_whole_history():
    # 80 months wobbling between 0 and 1, then a jump to 5: highest level and largest move
    pts = monthly([i % 2 for i in range(80)] + [5])
    s = signal_stats(pts)
    assert s["level_rank"] == 1.0 and s["move_rank"] == 1.0
    assert s["change"] == 5 - pts[-4][2]
    assert level_sentence(s) == "Höher als in 100 % aller Monate seit 2000."
    assert move_sentence(s, "Pp.").startswith("+4,0 Pp. in drei Monaten: größer als 100 %")


def test_short_series_are_not_ranked():
    s = signal_stats(monthly(range(20)))
    assert s["level_rank"] is None and s["move_rank"] is None
    assert "Zu kurze Geschichte" in level_sentence(s)


def test_move_ranks_need_sixty_earlier_moves():
    ranks = move_ranks(monthly([i % 3 for i in range(70)]))
    first = min(ranks)
    assert first == "2005-04"  # 3 months for the first change, then 60 earlier changes


def test_record_takes_the_largest_move_in_a_layer_and_spreads_quarters():
    sigs = [
        {"layer": "a", "indicator": "x", "move_ranks": {"2008-01": 0.2, "2008-02": 0.9}},
        {"layer": "a", "indicator": "y", "move_ranks": {"2008-01": 0.7}},
        {"layer": "b", "indicator": "z", "move_ranks": {"2008-Q1": 0.5}},
    ]
    rec = record(sigs, ["a", "b"], "2008-03")
    assert rec["months"] == ["2008-01", "2008-02", "2008-03"]
    assert rec["rows"]["a"] == [(0.7, "y"), (0.9, "x"), None]
    assert rec["rows"]["b"] == [(0.5, "z")] * 3


def test_colour_scale_is_continuous_and_monotone():
    shades = [heat_opacity(x / 100) for x in range(101)]
    assert shades == sorted(shades) and shades[0] == 0 and shades[-1] == 1


def test_rankings_order_by_rarity():
    sigs = [
        {"move_rank": 0.3, "level_rank": 0.5},
        {"move_rank": 0.9, "level_rank": 0.02},
        {"move_rank": None, "level_rank": 0.97},
    ]
    assert [s["move_rank"] for s in top_moves(sigs, 2)] == [0.9, 0.3]
    assert [s["level_rank"] for s in top_levels(sigs, 2)] == [0.02, 0.97]


def test_breadth_counts_states_in_the_direction_of_the_eu_trend():
    r = {"members": 27, "trend_now": -0.05, "rising_now": 3, "falling_now": 24,
         "members_before": 26, "rising_before": 15, "falling_before": 11}  # fmt: skip
    assert breadth_sentence(r) == (
        "Fallender Trend in 24 von 27 Mitgliedstaaten, in den fünf Jahren davor in 11 von 26."
    )


def _payload():
    pts = monthly([i % 2 for i in range(80)] + [5])
    sig = {
        "layer": "prices_policy", "indicator": "ea_hicp_headline_yoy", "knowledge": "vintage",
        **signal_stats(pts), "move_ranks": move_ranks(pts),
        "history": [[p[1], p[2]] for p in pts[-12:]], "sources": ["ecb_hicp"],
    }  # fmt: skip
    return {
        "model_version": "test",
        "generated_utc": "2026-10-03T12:00:00+00:00",
        "layers": ["prices_policy"],
        "signals": [sig],
        "record": record([sig], ["prices_policy"], "2008-03"),
        "events": [{"month": "2008-02", "text": "Ereignis"}],
        "structural": [],
        "sources": [{"card": "ecb_hicp", "provider": "ECB", "name": "HICP", "datasets": "ECB:HICP",
                     "licence": "free reuse", "url": "https://example.org/a?b=1&c=<2>",
                     "retrieved": "2026-10-03"}],
    }  # fmt: skip


def test_page_names_source_escapes_it_and_carries_no_verdict():
    html = render(_payload())
    assert html.startswith("<title>Lagebild Europa</title>")
    assert "Quelle: ECB · ECB:HICP, abgerufen 3. Oktober 2026 · Daten bis 09/2006" in html
    assert "c=&lt;2&gt;" in html and "<2>" not in html
    for verdict in ("ruhig", "ungewöhnlich schnell", "Tempo üblich", "Alarm"):
        assert verdict not in html
