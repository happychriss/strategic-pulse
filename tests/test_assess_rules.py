from srm.assess import (
    acceleration,
    data_quality,
    direction,
    evidence_strength,
    net_score,
    position,
    regime_paths,
)
from srm.regimes import ConditionResult


def cond(role, met, period="2024-11", age=0):
    return ConditionResult(
        "r",
        "k",
        role,
        "i",
        "level",
        ">",
        0.0,
        1.0 if met is not None else None,
        period if met is not None else None,
        None,
        age if met is not None else None,
        met,
        "x",
    )


def test_position_rules():
    assert (
        position([cond("supporting", True)] * 4 + [cond("opposing", False)] * 2)
        == "strongly supported"
    )
    assert (
        position([cond("supporting", True)] * 4 + [cond("opposing", True), cond("opposing", False)])
        == "supported"
    )
    assert (
        position(
            [
                cond("supporting", True),
                cond("supporting", False),
                cond("opposing", True),
                cond("opposing", False),
            ]
        )
        == "mixed"
    )
    assert (
        position([cond("supporting", False)] * 2 + [cond("opposing", True)] * 2) == "not supported"
    )


def test_net_score_and_direction():
    assert (
        net_score([cond("supporting", True), cond("supporting", False), cond("opposing", False)])
        == 0.5
    )
    assert direction(0.5) == "strongly_increasing"
    assert direction(0.2) == "increasing"
    assert direction(0.0) == "broadly_stable"
    assert direction(-0.2) == "decreasing"
    assert direction(-0.5) == "strongly_decreasing"


def test_acceleration():
    assert acceleration(0.5, 0.2) == "strengthening"
    assert acceleration(0.2, 0.5) == "weakening"
    assert acceleration(0.05, 0.5) == "none"


def test_data_quality_penalises_gaps_and_staleness():
    assert data_quality([cond("supporting", True)] * 4) == "high"
    assert data_quality([cond("supporting", True)] * 3 + [cond("supporting", None)]) == "medium"
    assert (
        data_quality(
            [cond("supporting", True, "2023-01", age=12)] * 2 + [cond("supporting", None)] * 2
        )
        == "low"
    )


def test_unreviewed_claims_do_not_count_as_evidence():
    proposed = [{"review_status": "proposed", "stance": "supports"}] * 5
    assert evidence_strength(proposed) == "low"
    accepted = [{"review_status": "accepted", "stance": "supports"}]
    assert evidence_strength(accepted) == "medium"


def test_regime_paths_multiply_signs_along_the_graph():
    edges = [
        {"key": "a", "src": "energy", "dst": "core", "sign": 1},
        {"key": "b", "src": "core", "dst": "hfl", "sign": 1},
        {"key": "c", "src": "energy", "dst": "output", "sign": -1},
        {"key": "d", "src": "output", "dst": "rd", "sign": -1},
    ]
    paths = regime_paths("core", 1, edges, {"hfl", "rd"})
    assert paths == {"hfl": (1, ["b"])}
    assert regime_paths("output", -1, edges, {"hfl", "rd"}) == {"rd": (1, ["d"])}
