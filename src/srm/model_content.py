"""Load versioned model content (model/*.yaml) into the model schema.

Definitions live in model/versions/<label>.yaml, one frozen file per model version, and all
of them are loaded so older assessments stay reproducible. model/current.yaml names the version
used for new assessments. If a version file changes after it was loaded, loading fails. Documents and claims are evidence; they
are upserted on every build, and each claim's passage must appear verbatim in its archived
source document.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import psycopg
import yaml

from srm.documents import passage_in_document
from srm.snapshot import RAW_DIR

MODEL_DIR = RAW_DIR.parents[1] / "model"
TRANSFORMS = {
    "identity",
    "yoy_pct",
    "qoq_pct",
    "compound_4q",
    "step_monthly",
    "monthly_mean",
    "mean_12m",
}


class ModelContentError(RuntimeError):
    pass


def read(name: str, model_dir: Path = MODEL_DIR) -> dict[str, Any]:
    return yaml.safe_load((model_dir / name).read_text(encoding="utf-8"))


def version_files(model_dir: Path = MODEL_DIR) -> list[Path]:
    return sorted((model_dir / "versions").glob("*.yaml"))


def current_label(model_dir: Path = MODEL_DIR) -> str:
    return read("current.yaml", model_dir)["current"]


def current_definitions(model_dir: Path = MODEL_DIR) -> dict[str, Any]:
    return read(f"versions/{current_label(model_dir)}.yaml", model_dir)


def definitions_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def end_of_day(d: date | str) -> datetime:
    """Knowledge time of a document: the end of its publication day (UTC), erring late."""
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return datetime.combine(d + timedelta(days=1), time(0), tzinfo=UTC)


def _series_uuid(family: str, series_key: str) -> str:
    from srm.build import stable_uuid  # local import avoids a cycle

    return stable_uuid(family, series_key)


def _range(lo: str | None, hi: str | None) -> str:
    return f"[{lo or ''},{hi or ''})"


def sync_model(conn: psycopg.Connection, model_dir: Path = MODEL_DIR) -> dict[str, int]:
    report = {"model_version_created": 0, "documents": 0, "claims": 0}
    versions: dict[str, int] = {}
    with conn.transaction():
        for path in version_files(model_dir):
            m = yaml.safe_load(path.read_text(encoding="utf-8"))
            label = m["model_version"]["label"]
            if path.stem != label:
                raise ModelContentError(f"{path.name}: label {label!r} must match the file name")
            digest = definitions_sha256(path)
            row = conn.execute(
                "SELECT model_version_id, definition_sha256 FROM model.model_version WHERE label = %s",
                (label,),
            ).fetchone()
            if row and row[1] != digest:
                raise ModelContentError(
                    f"{path.name} changed after it was loaded; released versions are frozen, "
                    "so create a new version file instead"
                )
            if row:
                versions[label] = row[0]
            else:
                versions[label] = _create_version(conn, m, label, digest)
                report["model_version_created"] += 1
        current = current_label(model_dir)
        if current not in versions:
            raise ModelContentError(f"model/current.yaml names unknown version {current!r}")
        mv = versions[current]

        docs = read("documents.yaml", model_dir)["documents"]
        for d in docs:
            conn.execute(
                """INSERT INTO model.document (doc_key, title, publisher, url, published_at)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (doc_key) DO UPDATE SET title=EXCLUDED.title, publisher=EXCLUDED.publisher,
                       url=EXCLUDED.url, published_at=EXCLUDED.published_at""",
                (d["id"], d["title"], d["publisher"], d["url"], end_of_day(d["published_on"])),
            )
        report["documents"] = len(docs)
        doc_ids = dict(conn.execute("SELECT doc_key, document_id FROM model.document").fetchall())

        edges = {
            k
            for (k,) in conn.execute(
                "SELECT edge_key FROM model.edge WHERE model_version_id = %s", (mv,)
            ).fetchall()
        }
        nodes = {
            k
            for (k,) in conn.execute(
                "SELECT code FROM model.node WHERE model_version_id = %s", (mv,)
            ).fetchall()
        }
        c = read("claims.yaml", model_dir)
        defaults = c.get("defaults", {})
        for cl in c["claims"]:
            kind, key = cl["target"].split(":", 1)
            if (kind == "edge" and key not in edges) or (kind == "node" and key not in nodes):
                raise ModelContentError(f"claim {cl['key']}: unknown target {cl['target']}")
            if cl["doc"] not in doc_ids:
                raise ModelContentError(f"claim {cl['key']}: unknown document {cl['doc']}")
            if not passage_in_document(cl["passage"], cl["doc"]):
                raise ModelContentError(
                    f"claim {cl['key']}: passage not found verbatim in {cl['doc']}"
                )
            conn.execute(
                """INSERT INTO model.evidence_claim (claim_key, document_id, locator, passage, statement,
                       stance, target_kind, target_key, region_code, strength, extracted_by,
                       review_status, reviewed_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'EA',%s,%s,%s,%s)
                   ON CONFLICT (claim_key) DO UPDATE SET document_id=EXCLUDED.document_id,
                       locator=EXCLUDED.locator, passage=EXCLUDED.passage, statement=EXCLUDED.statement,
                       stance=EXCLUDED.stance, target_kind=EXCLUDED.target_kind,
                       target_key=EXCLUDED.target_key, strength=EXCLUDED.strength,
                       extracted_by=EXCLUDED.extracted_by, review_status=EXCLUDED.review_status,
                       reviewed_by=EXCLUDED.reviewed_by""",
                (
                    cl["key"],
                    doc_ids[cl["doc"]],
                    cl["locator"],
                    cl["passage"],
                    cl["statement"],
                    cl["stance"],
                    kind,
                    key,
                    cl.get("strength"),
                    cl.get("extracted_by", defaults.get("extracted_by", "human")),
                    cl.get("review_status", defaults.get("review_status", "proposed")),
                    cl.get("reviewed_by"),
                ),
            )
        report["claims"] = len(c["claims"])
    return report


def _create_version(conn: psycopg.Connection, m: dict[str, Any], label: str, digest: str) -> int:
    mv = conn.execute(
        "INSERT INTO model.model_version (label, definition_sha256, notes) VALUES (%s,%s,%s) "
        "RETURNING model_version_id",
        (label, digest, m["model_version"].get("notes")),
    ).fetchone()[0]
    node_ids = {}
    for n in m["nodes"]:
        node_ids[n["code"]] = conn.execute(
            """INSERT INTO model.node (kind, code, label, definition, low_pole, high_pole, model_version_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING node_id""",
            (
                n["kind"],
                n["code"],
                n["label"],
                n["definition"].strip(),
                n.get("low_pole"),
                n.get("high_pole"),
                mv,
            ),
        ).fetchone()[0]
    ind_ids = {}
    for ind in m["indicators"]:
        if ind["node"] not in node_ids:
            raise ModelContentError(f"indicator {ind['code']}: unknown node {ind['node']}")
        ind_ids[ind["code"]] = conn.execute(
            """INSERT INTO model.indicator (code, label, node_id, region_code, unit, semantics,
                   definition, model_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING indicator_id""",
            (
                ind["code"],
                ind["label"],
                node_ids[ind["node"]],
                ind["region"],
                ind.get("unit"),
                ind["semantics"],
                ind["definition"].strip(),
                mv,
            ),
        ).fetchone()[0]
        for comp in ind["components"]:
            if comp["transform"] not in TRANSFORMS:
                raise ModelContentError(f"{ind['code']}: unknown transform {comp['transform']}")
            sid = _series_uuid(comp["family"], comp["series_key"])
            if not conn.execute("SELECT 1 FROM obs.series WHERE series_id = %s", (sid,)).fetchone():
                raise ModelContentError(
                    f"{ind['code']}: series {comp['family']} {comp['series_key']} not loaded"
                )
            conn.execute(
                """INSERT INTO model.indicator_component (indicator_id, role, series_id, serves, transform, note)
                   VALUES (%s,%s,%s,%s::tstzrange,%s,%s)""",
                (
                    ind_ids[ind["code"]],
                    comp.get("role", "value"),
                    sid,
                    _range(comp.get("serves_from"), comp.get("serves_to")),
                    comp["transform"],
                    comp.get("note"),
                ),
            )
    for e in m["edges"]:
        for end in ("src", "dst"):
            if e[end] not in node_ids:
                raise ModelContentError(f"edge {e['key']}: unknown node {e[end]}")
        lag = e.get("lag") or [None, None]
        conn.execute(
            """INSERT INTO model.edge (edge_key, src_node, dst_node, rel_type, expected_sign, lag_min,
                   lag_max, region_code, evidence_status, proposed_evidence_status, model_version_id, note)
               VALUES (%s,%s,%s,%s,%s,%s::interval,%s::interval,%s,%s,%s,%s,%s)""",
            (
                e["key"],
                node_ids[e["src"]],
                node_ids[e["dst"]],
                e["rel_type"],
                e.get("sign"),
                lag[0],
                lag[1],
                e.get("region"),
                e.get("status", "hypothesis"),
                e.get("proposed_status"),
                mv,
                e.get("note"),
            ),
        )
    for rc in m["regime_conditions"]:
        conn.execute(
            """INSERT INTO model.regime_condition (model_version_id, condition_key, regime_node,
                   indicator_id, metric, comparator, threshold, role, rationale)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                mv,
                rc["key"],
                node_ids[rc["regime"]],
                ind_ids[rc["indicator"]],
                rc["metric"],
                rc["op"],
                rc["threshold"],
                rc["role"],
                rc["rationale"],
            ),
        )
    return mv
