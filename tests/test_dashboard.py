from srm.dashboard import (
    LAYERS_DE,
    SIGNALS_DE,
    STRUCTURAL_DE,
    _years,
    headline,
    num,
    period_de,
    render,
    trend_words,
)
from srm.detect import config
from srm.structural import config as structural_config


def test_german_number_format():
    assert num(3.8) == "3,8"
    assert num(-16.5) == "−16,5"
    assert num(1.0, 1, True) == "+1,0"
    assert num(None) == "–"


def test_periods_read_the_german_way():
    assert period_de("2026-09") == "09/2026"
    assert period_de("2026-Q2") == "Q2/2026"
    assert period_de("2024") == "2024"


def test_year_runs_are_compressed():
    assert _years([2011, 2012, 2013, 2015, 2022]) == "2011–2013, 2015, 2022"


def test_trend_words():
    assert trend_words(-0.049, -0.005, 1.34, False) == "fällt schneller"
    assert trend_words(0.46, 0.6, 34.5, False) == "steigt langsamer"
    assert trend_words(-0.35, 1.04, 49.5, True) == "Trend dreht: fällt jetzt"
    assert trend_words(-0.0015, -0.0003, 1.13, False) == "seitwärts"
    assert trend_words(None, 0.1, 1.0, False).startswith("Trend nicht")


def test_every_signal_layer_and_axis_of_the_current_model_has_a_german_name():
    cfg = config()
    assert {layer["key"] for layer in cfg["layers"]} <= set(LAYERS_DE)
    sigs = {s["indicator"] for layer in cfg["layers"] for s in layer["signals"]}
    assert sigs <= set(SIGNALS_DE)
    assert {i["key"] for i in structural_config()["indicators"]} <= set(STRUCTURAL_DE)


def _payload(level, active, unusual=False, turn=False):
    sig = {
        "layer": "prices_policy", "indicator": "ea_hicp_headline_yoy", "knowledge": "vintage",
        "latest_period": "2026-09", "value": 3.8, "change": 1.0, "threshold": 1.6,
        "history_months": 300, "unusual": unusual, "turn": turn, "change_6m": 1.2, "note": "",
        "history": [["2026-07", 2.8], ["2026-08", 3.4], ["2026-09", 3.8]], "sources": ["ecb_hicp"],
    }  # fmt: skip
    return {
        "model_version": "test",
        "generated_utc": "2026-10-03T12:00:00+00:00",
        "now": {"month": "2026-10", "level": level, "onset": False, "active_layers": active,
                "recent": [{"month": "2026-10", "level": level, "onset": False}]},
        "layers": [{"key": "prices_policy", "label": "Prices"}],
        "signals": [sig],
        "timeline": [{"month": "2026-10", "level": level, "onset": False, "layers": active}],
        "events": [],
        "test": {"events": [], "false_alarms": [], "onsets": 0, "alarm_months": 0, "months": 1},
        "structural": [],
        "structural_flagged_years": {},
        "sources": [{"card": "ecb_hicp", "provider": "ECB", "name": "HICP", "datasets": "ECB:HICP",
                     "licence": "free reuse", "url": "https://example.org/a?b=1&c=<2>",
                     "retrieved": "2026-10-03"}],
    }  # fmt: skip


def test_headline_follows_the_level():
    assert headline(_payload(0, []))[0] == "calm"
    state, text = headline(_payload(1, ["prices_policy"], turn=True))
    assert state == "move" and "Preise und Geldpolitik" in text
    assert headline(_payload(2, ["prices_policy", "real_economy"]))[0] == "alarm"


def test_page_names_source_and_escapes_it():
    html = render(_payload(1, ["prices_policy"], unusual=True))
    assert html.startswith("<title>Lagebild Europa</title>")
    assert "Quelle: ECB · ECB:HICP, abgerufen 3. Oktober 2026 · Daten bis 09/2026" in html
    assert "ungewöhnlich schneller Anstieg" in html
    assert "c=&lt;2&gt;" in html and "<2>" not in html
