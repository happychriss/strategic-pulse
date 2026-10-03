import copy

from srm.snapshot import RAW_DIR
from srm.source_cards import load_cards, validate


def test_all_cards_are_valid():
    cards = load_cards()
    assert cards, "no source cards found"
    for card in cards:
        assert validate(card.data, card.path.stem) == [], card.path.name


def test_ids_are_unique():
    ids = [c.id for c in load_cards()]
    assert len(ids) == len(set(ids))


def test_unverified_cards_do_not_claim_a_date():
    for card in load_cards():
        v = card.data["verification"]
        if v["status"] == "unverified":
            assert v["date"] is None, card.path.name


def test_verified_cards_have_an_archived_snapshot():
    for card in load_cards():
        if card.data["verification"]["status"] == "verified":
            metas = list((RAW_DIR / card.id).glob("*.meta.json"))
            assert metas, f"{card.id} is verified but has no snapshot in data/raw"


def test_superseded_by_points_to_an_existing_card():
    ids = {c.id for c in load_cards()}
    for card in load_cards():
        target = card.data.get("superseded_by")
        if target:
            assert target in ids, f"{card.id} superseded_by unknown card {target}"


def test_validator_rejects_broken_card():
    good = load_cards()[0].data
    bad = copy.deepcopy(good)
    del bad["temporal"]["vintage_support"]
    assert any("vintage_support" in p for p in validate(bad))
    bad = copy.deepcopy(good)
    bad["verification"] = {"status": "verified", "date": None, "note": "x"}
    assert any("verification.date" in p for p in validate(bad))
