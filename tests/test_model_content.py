"""Integrity of the versioned model content, checked without a database."""

import re
from collections import defaultdict

import yaml

from srm.documents import latest_document_file, passage_in_document
from srm.model_content import MODEL_DIR, TRANSFORMS, current_definitions, version_files
from srm.parsers import read_bytes

M = current_definitions()
DOCS = yaml.safe_load((MODEL_DIR / "documents.yaml").read_text())["documents"]
CLAIMS = yaml.safe_load((MODEL_DIR / "claims.yaml").read_text())
NODES = {n["code"]: n for n in M["nodes"]}
EDGES = {e["key"]: e for e in M["edges"]}


def claims():
    d = CLAIMS.get("defaults", {})
    return [{**d, **c} for c in CLAIMS["claims"]]


def test_every_passage_is_verbatim_in_its_archived_document():
    missing = [c["key"] for c in claims() if not passage_in_document(c["passage"], c["doc"])]
    assert missing == []


def test_document_dates_match_the_page_metadata():
    for d in DOCS:
        raw = read_bytes(latest_document_file(d["id"])).decode("utf-8", errors="replace")
        meta = re.search(r'article:published_time"\s+content="(\d{4}-\d{2}-\d{2})', raw)
        assert meta, d["id"]
        assert str(d["published_on"]) == meta.group(1), d["id"]


def test_references_resolve():
    doc_ids = {d["id"] for d in DOCS}
    for c in claims():
        kind, key = c["target"].split(":", 1)
        assert key in (EDGES if kind == "edge" else NODES), c["key"]
        assert c["doc"] in doc_ids, c["key"]
    for e in M["edges"]:
        assert e["src"] in NODES and e["dst"] in NODES, e["key"]
    for i in M["indicators"]:
        assert i["node"] in NODES, i["code"]
        assert all(comp["transform"] in TRANSFORMS for comp in i["components"])


def test_mechanism_edges_have_supporting_evidence():
    supporting = defaultdict(int)
    for c in claims():
        if c["stance"] == "supports" and c["target"].startswith("edge:"):
            supporting[c["target"][5:]] += 1
    for key, e in EDGES.items():
        if e.get("proposed_status", "hypothesis") != "hypothesis":
            assert supporting[key] >= 1, f"{key} proposes {e['proposed_status']} without support"


def test_no_edge_is_promoted_without_accepted_evidence():
    accepted = defaultdict(int)
    for c in claims():
        if (
            c["stance"] == "supports"
            and c["review_status"] == "accepted"
            and c["target"].startswith("edge:")
        ):
            assert c["extracted_by"] == "human" or c.get("reviewed_by"), c["key"]
            accepted[c["target"][5:]] += 1
    for key, e in EDGES.items():
        if e.get("status", "hypothesis") != "hypothesis":
            assert accepted[key] >= 1, (
                f"{key} is {e['status']} without an accepted supporting claim"
            )


def test_counter_evidence_is_present():
    stances = {c["stance"] for c in claims()}
    assert {"supports", "contradicts", "qualifies"} <= stances


def test_every_regime_has_supporting_and_opposing_conditions():
    roles = defaultdict(set)
    for rc in M["regime_conditions"]:
        roles[rc["regime"]].add(rc["role"])
    regimes = [n for n, v in NODES.items() if v["kind"] == "regime"]
    for r in regimes:
        assert roles[r] == {"supporting", "opposing"}, r


def test_every_axis_and_state_variable_has_an_indicator():
    covered = {i["node"] for i in M["indicators"]}
    for code, n in NODES.items():
        if n["kind"] in ("structural_axis", "state_variable"):
            assert code in covered, code


def test_version_files_are_named_by_label_and_current_exists():
    labels = []
    for path in version_files():
        label = yaml.safe_load(path.read_text())["model_version"]["label"]
        assert path.stem == label
        labels.append(label)
    assert M["model_version"]["label"] in labels
