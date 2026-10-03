"""Assessment engine: regimes, relationships and their evidence as of a knowledge instant.

    python -m srm.assess 2019-12-31 2021-12-31 2022-12-31 2024-12-31 now

The rules below are the assessment methodology (ENGINE_VERSION). They are deliberately
simple and qualitative (concept section 8): no probabilities, explicit thresholds, every
judgement traceable to stored inputs.

Position     net = share of supporting conditions met - share of opposing conditions met
             >= 0.75 with no opposing met: strongly supported; >= 0.25: supported;
             > -0.25: mixed; otherwise not supported.
Direction    change in net versus six months earlier: >= 0.4 strongly increasing,
             >= 0.15 increasing, <= -0.15 decreasing, <= -0.4 strongly decreasing.
Data quality share of conditions evaluable and freshness of their latest data
             (stale: monthly > 3, quarterly > 6, annual > 18 months old).
Evidence     only reviewed (accepted) claims count; unreviewed claims are shown, not counted.
Dynamics     a relationship is active when its source indicator moved by more than
             MOVE_THRESHOLD points over 12 months; its effect on a regime is the product
             of signs along the path through the relationship graph.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, time

import psycopg

from srm.indicators import _add_months, current_version, indicator_series_with_inputs, metric
from srm.periods import parse_period
from srm.regimes import ConditionResult, evaluate

ENGINE_VERSION = "assess-0.1"
MOVE_THRESHOLD = 0.25
STALE_MONTHS = {"D": 1, "M": 3, "Q": 6, "S": 9, "A": 18}


# ------------------------------------------------------------------ rules (pure)
def net_score(conds: list[ConditionResult]) -> float:
    sup = [c for c in conds if c.role == "supporting"]
    opp = [c for c in conds if c.role == "opposing"]
    s = sum(bool(c.met) for c in sup) / len(sup) if sup else 0.0
    o = sum(bool(c.met) for c in opp) / len(opp) if opp else 0.0
    return round(s - o, 4)


def position(conds: list[ConditionResult]) -> str:
    net = net_score(conds)
    opp_met = any(c.met for c in conds if c.role == "opposing")
    if net >= 0.75 and not opp_met:
        return "strongly supported"
    if net >= 0.25:
        return "supported"
    if net > -0.25:
        return "mixed"
    return "not supported"


def direction(delta: float) -> str:
    if delta >= 0.4:
        return "strongly_increasing"
    if delta >= 0.15:
        return "increasing"
    if delta <= -0.4:
        return "strongly_decreasing"
    if delta <= -0.15:
        return "decreasing"
    return "broadly_stable"


def velocity(delta: float) -> str:
    a = abs(delta)
    return "low" if a < 0.15 else "medium" if a < 0.4 else "high"


def acceleration(delta_now: float, delta_before: float) -> str:
    if abs(delta_now) < 0.15:
        return "none"
    if (
        delta_before == 0
        or (delta_now > 0) != (delta_before > 0)
        or abs(delta_now) > abs(delta_before)
    ):
        return "strengthening"
    return "weakening"


def is_stale(c: ConditionResult) -> bool:
    if c.latest_period is None:
        return False
    freq = parse_period(c.latest_period)[2]
    return (c.age_months or 0) > STALE_MONTHS[freq]


def data_quality(conds: list[ConditionResult]) -> str:
    evaluable = [c for c in conds if c.met is not None]
    stale = [c for c in evaluable if is_stale(c)]
    share = len(evaluable) / len(conds) if conds else 0
    if share == 1 and not stale:
        return "high"
    if share >= 0.75 and len(stale) <= 1:
        return "medium"
    return "low"


def evidence_strength(claims: list[dict]) -> str:
    accepted = [c for c in claims if c["review_status"] == "accepted" and c["stance"] == "supports"]
    if len(accepted) >= 3:
        return "high"
    if accepted:
        return "medium"
    return "low"


def model_confidence(pos: str, dq: str) -> str:
    if dq == "low" or pos == "mixed":
        return "low"
    if pos in ("strongly supported", "not supported") and dq == "high":
        return "high"
    return "medium"


# ------------------------------------------------------------------ data structures
@dataclass
class EdgeResult:
    edge_id: str
    key: str
    src: str
    dst: str
    sign: int
    indicator: str | None
    change_12m: float | None
    change_6m: float | None
    latest_period: str | None
    movement: int  # +1 toward src high pole, -1 toward low pole, 0 not moving
    state: str
    implications: dict[str, int] = field(default_factory=dict)  # regime -> +1 / -1
    paths: dict[str, list[str]] = field(default_factory=dict)
    inputs: list = field(default_factory=list)


@dataclass
class RegimeResult:
    node_id: str
    code: str
    label: str
    position: str
    net: float
    net_6m_ago: float
    direction: str
    velocity: str
    acceleration: str
    data_quality: str
    evidence_strength: str
    model_confidence: str
    summary: str
    would_change_view: str
    conditions: list[ConditionResult]
    drivers: list[str]
    counterforces: list[str]
    claims: list[dict]


# ------------------------------------------------------------------ engine
def _graph(conn, mv):
    nodes = {
        r[0]: {"id": r[0], "code": r[1], "kind": r[2], "label": r[3]}
        for r in conn.execute(
            "SELECT node_id::text, code, kind, label FROM model.node WHERE model_version_id = %s",
            (mv,),
        ).fetchall()
    }
    edges = [
        {
            "id": r[0],
            "key": r[1],
            "src": nodes[r[2]]["code"],
            "dst": nodes[r[3]]["code"],
            "sign": r[4] or 0,
        }
        for r in conn.execute(
            """SELECT edge_id::text, edge_key, src_node::text, dst_node::text, expected_sign
               FROM model.edge WHERE model_version_id = %s ORDER BY edge_key""",
            (mv,),
        ).fetchall()
    ]
    return nodes, edges


def regime_paths(start: str, sign: int, edges: list[dict], regimes: set[str], depth: int = 4):
    """Effect of a push on `start` on each regime, following edges; first path found wins."""
    out: dict[str, tuple[int, list[str]]] = {}

    def walk(node: str, s: int, path: list[str], d: int):
        if node in regimes:
            out.setdefault(node, (s, path))
            return
        if d == 0:
            return
        for e in edges:
            if e["src"] == node and e["key"] not in path:
                walk(e["dst"], s * e["sign"], path + [e["key"]], d - 1)

    walk(start, sign, [], depth)
    return out


def _node_indicator(conn, mv, node_code):
    return conn.execute(
        """SELECT i.code, i.semantics FROM model.indicator i JOIN model.node n USING (node_id)
           WHERE n.code = %s AND i.model_version_id = %s ORDER BY i.code LIMIT 1""",
        (node_code, mv),
    ).fetchone()


def assess_edges(conn, at, mv, nodes, edges) -> list[EdgeResult]:
    regimes = {n["code"] for n in nodes.values() if n["kind"] == "regime"}
    out = []
    for e in edges:
        if e["dst"] in regimes and e["src"] in regimes:
            continue
        ind = _node_indicator(conn, mv, e["src"])
        r = EdgeResult(
            e["id"],
            e["key"],
            e["src"],
            e["dst"],
            e["sign"],
            None,
            None,
            None,
            None,
            0,
            "unsupported",
        )
        if ind:
            code, semantics = ind
            pts, inputs = indicator_series_with_inputs(conn, code, at, mv)
            m12, m6 = metric(pts, "change_12m"), metric(pts, "change_6m")
            r.indicator = code
            if m12:
                pole = -1 if semantics == "higher_is_toward_low_pole" else 1
                r.change_12m, r.latest_period = m12[0], m12[1]
                r.change_6m = m6[0] if m6 else None
                start = parse_period(m12[1])[0]
                r.inputs = list(inputs.get(start, [])) + list(
                    inputs.get(parse_period(m12[2])[0], [])
                )
                if abs(m12[0]) > MOVE_THRESHOLD:
                    r.movement = pole * (1 if m12[0] > 0 else -1)
                    if r.change_6m is not None and (r.change_6m > 0) != (m12[0] > 0):
                        r.state = "weakening"
                    elif r.change_6m is not None and abs(r.change_6m) > abs(m12[0]) / 2:
                        r.state = "strengthening"
                    else:
                        r.state = "active"
                else:
                    r.state = "conditional"
        if r.movement:
            push = r.movement * e["sign"]
            if e["dst"] in regimes:
                r.implications[e["dst"]] = push
                r.paths[e["dst"]] = [e["key"]]
            else:
                for reg, (s, path) in regime_paths(e["dst"], push, edges, regimes).items():
                    r.implications[reg] = s
                    r.paths[reg] = [e["key"], *path]
        out.append(r)
    return out


def _claims_known(conn, at, targets: list[tuple[str, str]]) -> list[dict]:
    if not targets:
        return []
    rows = conn.execute(
        """SELECT c.claim_id::text, c.claim_key, c.stance, c.statement, c.passage, c.locator,
                  c.review_status, c.extracted_by, c.reviewed_by, c.target_kind, c.target_key,
                  d.doc_key, d.title, d.url, d.published_at
           FROM model.evidence_claim c JOIN model.document d USING (document_id)
           WHERE d.published_at <= %s AND (c.target_kind, c.target_key) IN (SELECT * FROM unnest(%s::text[], %s::text[]))
           ORDER BY d.published_at, c.claim_key""",
        (at, [t[0] for t in targets], [t[1] for t in targets]),
    ).fetchall()
    keys = [
        "claim_id",
        "key",
        "stance",
        "statement",
        "passage",
        "locator",
        "review_status",
        "extracted_by",
        "reviewed_by",
        "target_kind",
        "target_key",
        "doc_key",
        "doc_title",
        "url",
        "published_at",
    ]
    return [dict(zip(keys, r, strict=True)) for r in rows]


def _summary(label, pos, conds, dirn):
    sup = [c for c in conds if c.role == "supporting"]
    opp = [c for c in conds if c.role == "opposing"]
    text = (
        f"Evidence for {label.lower()} is {pos}: {sum(bool(c.met) for c in sup)} of {len(sup)} "
        f"supporting and {sum(bool(c.met) for c in opp)} of {len(opp)} opposing conditions met; "
        f"{dirn.replace('_', ' ')} over six months."
    )
    missing = [c.key for c in conds if c.met is None]
    if missing:
        text += f" Not evaluable with data known then: {', '.join(missing)}."
    return text


def _would_change(conds):
    parts = []
    for c in conds:
        if c.met is None:
            continue
        cur = f"{c.value:.2f}"
        if c.role == "opposing" and not c.met:
            parts.append(
                f"weaker if {c.indicator} {c.metric} {c.comparator} {c.threshold:g} (now {cur})"
            )
        if c.role == "supporting" and c.met:
            parts.append(
                f"weaker if {c.indicator} {c.metric} no longer {c.comparator} {c.threshold:g} (now {cur})"
            )
        if c.role == "supporting" and not c.met:
            parts.append(
                f"stronger if {c.indicator} {c.metric} {c.comparator} {c.threshold:g} (now {cur})"
            )
    return "; ".join(parts)


def assess(conn: psycopg.Connection, at: datetime, model_version_id: int | None = None) -> dict:
    mv = model_version_id or current_version(conn)
    nodes, edges = _graph(conn, mv)
    regimes = [n for n in nodes.values() if n["kind"] == "regime"]
    now_c = evaluate(conn, at, mv)
    prev_c = evaluate(conn, _shift(at, -6), mv)
    prev2_c = evaluate(conn, _shift(at, -12), mv)
    edge_results = assess_edges(conn, at, mv, nodes, edges)
    results = []
    for reg in sorted(regimes, key=lambda n: n["code"]):
        code = reg["code"]
        conds = [c for c in now_c if c.regime == code]
        net = net_score(conds)
        net6 = net_score([c for c in prev_c if c.regime == code])
        net12 = net_score([c for c in prev2_c if c.regime == code])
        pos = position(conds)
        dq = data_quality(conds)
        link_edges = [e["key"] for e in edges if e["dst"] == code]
        drivers = [r.key for r in edge_results if r.implications.get(code) == 1]
        counter = [r.key for r in edge_results if r.implications.get(code) == -1]
        targets = [("node", code)] + [
            ("edge", k) for k in sorted(set(link_edges + drivers + counter))
        ]
        claims = _claims_known(conn, at, targets)
        es = evidence_strength(
            [c for c in claims if c["target_key"] in [code, *link_edges, *drivers]]
        )
        results.append(
            RegimeResult(
                reg["id"],
                code,
                reg["label"],
                pos,
                net,
                net6,
                direction(net - net6),
                velocity(net - net6),
                acceleration(net - net6, net6 - net12),
                dq,
                es,
                model_confidence(pos, dq),
                _summary(reg["label"], pos, conds, direction(net - net6)),
                _would_change(conds),
                conds,
                drivers,
                counter,
                claims,
            )
        )
    return {"at": at, "model_version_id": mv, "regimes": results, "edges": edge_results}


def _shift(at: datetime, months: int) -> datetime:
    d = _add_months(at.date().replace(day=1), months)
    day = min(at.day, 28)
    return datetime.combine(d.replace(day=day), at.timetz())


# ------------------------------------------------------------------ persistence
def persist(conn: psycopg.Connection, report: dict, region: str = "EA") -> str:
    at, mv = report["at"], report["model_version_id"]
    with conn.transaction():
        run_id = conn.execute(
            """INSERT INTO model.assessment_run (as_of, model_version_id, region_code, engine_version)
               VALUES (%s,%s,%s,%s) RETURNING run_id::text""",
            (at, mv, region, ENGINE_VERSION),
        ).fetchone()[0]
        edge_assessment = {}
        claims_by_edge: dict[str, list[dict]] = {}
        for r in report["regimes"]:
            for c in r.claims:
                if c["target_kind"] == "edge":
                    claims_by_edge.setdefault(c["target_key"], []).append(c)
        for e in report["edges"]:
            ec = claims_by_edge.get(e.key, []) or _claims_known(conn, at, [("edge", e.key)])
            aid = conn.execute(
                """INSERT INTO model.assessment (run_id, edge_id, region_code, as_of, model_version_id,
                       edge_state, data_quality, evidence_strength, model_confidence, summary, details)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING assessment_id::text""",
                (
                    run_id,
                    e.edge_id,
                    region,
                    at,
                    mv,
                    e.state,
                    "high" if e.change_12m is not None else "low",
                    evidence_strength(ec),
                    "medium" if e.change_12m is not None else "low",
                    _edge_summary(e),
                    json.dumps(_edge_details(e)),
                ),
            ).fetchone()[0]
            edge_assessment[e.key] = aid
            _insert_obs_inputs(conn, aid, e.inputs, "context", f"source indicator {e.indicator}")
            _insert_claim_inputs(conn, aid, ec)
        for r in report["regimes"]:
            aid = conn.execute(
                """INSERT INTO model.assessment (run_id, node_id, region_code, as_of, model_version_id,
                       position, direction, velocity, acceleration, data_quality, evidence_strength,
                       model_confidence, summary, would_change_view, details)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING assessment_id::text""",
                (
                    run_id,
                    r.node_id,
                    region,
                    at,
                    mv,
                    r.position,
                    r.direction,
                    r.velocity,
                    r.acceleration,
                    r.data_quality,
                    r.evidence_strength,
                    r.model_confidence,
                    r.summary,
                    r.would_change_view,
                    json.dumps(_regime_details(r)),
                ),
            ).fetchone()[0]
            for c in r.conditions:
                role = (
                    "context"
                    if not c.met
                    else ("supporting" if c.role == "supporting" else "contradicting")
                )
                _insert_obs_inputs(conn, aid, c.inputs, role, f"condition {c.key}")
            _insert_claim_inputs(conn, aid, r.claims)
            for k in r.drivers:
                _insert_assessment_input(conn, aid, edge_assessment[k], "supporting", f"driver {k}")
            for k in r.counterforces:
                _insert_assessment_input(
                    conn, aid, edge_assessment[k], "contradicting", f"counterforce {k}"
                )
    return run_id


def _insert_obs_inputs(conn, aid, keys, role, note):
    seen = set()
    for series_id, period, known_from in keys:
        k = (series_id, str(period), known_from)
        if k in seen:
            continue
        seen.add(k)
        conn.execute(
            """INSERT INTO model.assessment_input (assessment_id, role, series_id, period, known_from, note)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (aid, role, series_id, period, known_from, note),
        )


def _insert_claim_inputs(conn, aid, claims):
    role = {"supports": "supporting", "contradicts": "contradicting", "qualifies": "context"}
    for c in claims:
        conn.execute(
            "INSERT INTO model.assessment_input (assessment_id, role, claim_id, note) VALUES (%s,%s,%s,%s)",
            (aid, role[c["stance"]], c["claim_id"], f"claim {c['key']} ({c['review_status']})"),
        )


def _insert_assessment_input(conn, aid, input_aid, role, note):
    conn.execute(
        """INSERT INTO model.assessment_input (assessment_id, role, input_assessment_id, note)
           VALUES (%s,%s,%s,%s)""",
        (aid, role, input_aid, note),
    )


def _edge_summary(e: EdgeResult) -> str:
    if e.change_12m is None:
        return f"{e.key}: source indicator not evaluable with data known then."
    move = {1: "rising", -1: "falling", 0: "not moving"}[e.movement]
    return f"{e.key}: {e.indicator} {e.change_12m:+.2f} over 12 months ({move}); state {e.state}."


def _edge_details(e: EdgeResult) -> dict:
    d = asdict(e)
    d.pop("inputs")
    return d


def _regime_details(r: RegimeResult) -> dict:
    return {
        "net": r.net,
        "net_6m_ago": r.net_6m_ago,
        "conditions": [{k: v for k, v in asdict(c).items() if k != "inputs"} for c in r.conditions],
        "drivers": r.drivers,
        "counterforces": r.counterforces,
    }


def parse_as_of(text: str) -> datetime:
    if text == "now":
        return datetime.now(UTC)
    return datetime.combine(datetime.fromisoformat(text).date(), time(23, 0), tzinfo=UTC)


def main(argv: list[str]) -> int:
    from srm.db import connect
    from srm.report import write_reports

    dates = [parse_as_of(a) for a in argv] or [
        parse_as_of(a) for a in ("2019-12-31", "2021-12-31", "2022-12-31", "2024-12-31", "now")
    ]
    with connect() as conn:
        conn.autocommit = True
        runs = []
        for at in dates:
            report = assess(conn, at)
            runs.append(persist(conn, report))
            for r in report["regimes"]:
                print(
                    f"{at:%Y-%m-%d} {r.code:<24} {r.position:<18} {r.direction:<20} "
                    f"dq={r.data_quality} ev={r.evidence_strength} conf={r.model_confidence}"
                )
        from srm.detect import run as run_detector

        run_detector(conn)
        for path in write_reports(conn, runs):
            print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
