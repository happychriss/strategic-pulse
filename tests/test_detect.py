from datetime import UTC, date, datetime

from srm.detect import (
    Detection,
    SignalResult,
    evaluate_points,
    evaluate_turn,
    mark_onsets,
    quantile,
    score_events,
)


def monthly(values, start=(2010, 1)):
    y, m, out = *start, []
    for v in values:
        out.append((date(y, m, 1), f"{y}-{m:02d}", float(v)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_quantile():
    assert quantile([1, 2, 3, 4, 5], 0.5) == 3
    assert quantile([0, 10], 0.95) == 9.5


def test_a_jump_far_beyond_own_history_is_unusual():
    pts = monthly([1.0 + 0.01 * (i % 5) for i in range(80)] + [5.0])
    r = SignalResult("l", "i", "vintage")
    evaluate_points(pts, datetime(2016, 11, 15, tzinfo=UTC), 3, 0.95, 60, r)
    assert r.unusual is True and r.threshold < 1


def test_normal_noise_is_not_unusual_and_short_history_is_not_evaluable():
    pts = monthly([1.0 + 0.1 * ((i * 7) % 5) for i in range(80)])
    r = SignalResult("l", "i", "vintage")
    evaluate_points(pts, datetime(2016, 9, 15, tzinfo=UTC), 3, 0.95, 60, r)
    assert r.unusual is False
    short = SignalResult("l", "i", "vintage")
    evaluate_points(
        monthly([1, 2, 3, 4, 5, 6, 7, 8]), datetime(2010, 9, 15, tzinfo=UTC), 3, 0.95, 60, short
    )
    assert short.unusual is None and "short" in short.note


def test_stale_data_is_not_evaluable():
    r = SignalResult("l", "i", "vintage")
    evaluate_points(monthly([1.0] * 80), datetime(2020, 1, 15, tzinfo=UTC), 3, 0.95, 60, r)
    assert r.unusual is None and "stale" in r.note


def test_event_scoring_distinguishes_new_and_running_alarms():
    def det(y, m, level):
        at = datetime(y, m + 1, 1, tzinfo=UTC) if m < 12 else datetime(y + 1, 1, 1, tzinfo=UTC)
        return Detection(at, level, ["a", "b"] if level == 2 else [])

    dets = [det(2020, m, 0) for m in range(1, 13)]
    dets[3] = det(2020, 4, 2)  # new alarm inside the window of a March event
    dets[4] = det(2020, 5, 2)  # continuation, not a new alarm
    dets[11] = det(2020, 12, 2)  # new alarm outside any window
    mark_onsets(dets, 3)
    assert [d.onset for d in dets].count(True) == 2
    s = score_events(dets, [{"month": "2020-03", "label": "x"}])
    assert s["events"][0]["status"] == "new alarm" and s["events"][0]["lag_months"] == 1
    assert s["false_alarms"] == ["2020-12"]


def test_direction_change_after_a_consistent_run():
    rising = [float(i) * 0.1 for i in range(40)]
    pts = monthly(rising + [rising[-1] - 1.5])  # first month of a clear reversal
    r = SignalResult("l", "i", "vintage", unusual=False)
    evaluate_turn(pts, {"window_months": 6, "lookback_months": 12, "consistency": 0.75}, r)
    assert r.turn is True
    flat = SignalResult("l", "i", "vintage", unusual=False)
    evaluate_turn(
        monthly(rising), {"window_months": 6, "lookback_months": 12, "consistency": 0.75}, flat
    )
    assert flat.turn is False
