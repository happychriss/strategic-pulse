from datetime import UTC, date, datetime
from decimal import Decimal as D

from srm.knowledge import Event, collapse, edition_time, release_time, revdate_time


def t(day: int) -> datetime:
    return datetime(2024, 1, day, tzinfo=UTC)


def test_knowledge_rules_err_late():
    assert revdate_time("2020-07-31") == datetime(2020, 8, 1, tzinfo=UTC)
    assert edition_time("202312") == datetime(2024, 1, 1, tzinfo=UTC)
    assert edition_time("202304") == datetime(2023, 5, 1, tzinfo=UTC)
    assert release_time(date(2024, 1, 2), 1) == datetime(2024, 1, 3, tzinfo=UTC)


def test_identical_vintages_merge_and_changes_split():
    ivs = collapse([Event(t(1), D("7.5")), Event(t(2), D("7.5")), Event(t(3), D("7.6"))])
    assert [(i.known_from, i.known_to, i.value) for i in ivs] == [
        (t(1), t(3), D("7.5")),
        (t(3), None, D("7.6")),
    ]


def test_withdrawal_closes_interval():
    ivs = collapse([Event(t(1), D(1)), Event(t(5), None)])
    assert [(i.known_from, i.known_to) for i in ivs] == [(t(1), t(5))]


def test_replacement_beats_withdrawal_at_same_instant():
    ivs = collapse([Event(t(1), D(1)), Event(t(4), None), Event(t(4), D(2))])
    assert [(i.known_from, i.known_to, i.value) for i in ivs] == [
        (t(1), t(4), D(1)),
        (t(4), None, D(2)),
    ]


def test_dense_vintage_absence_closes_but_not_before_first_appearance():
    events = [Event(t(2), D(3)), Event(t(4), D(3))]
    ivs = collapse(events, vintage_times=[t(1), t(2), t(3), t(4)])
    # Missing at t1: not yet published (no interval). Missing at t3: withdrawn, reappears t4.
    assert [(i.known_from, i.known_to) for i in ivs] == [(t(2), t(3)), (t(4), None)]


def test_status_or_attribute_change_is_a_new_interval():
    ivs = collapse(
        [
            Event(t(1), D(100), attrs=(("BASE_PER", "2015"),)),
            Event(t(2), D(100), attrs=(("BASE_PER", "2021"),)),
        ]
    )
    assert len(ivs) == 2


def test_earliest_snapshot_wins_at_same_instant():
    ivs = collapse([Event(t(1), D(1), snapshot_id="a"), Event(t(1), D(1), snapshot_id="b")])
    assert ivs[0].snapshot_id == "a"
