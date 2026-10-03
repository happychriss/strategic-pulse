"""Integration tests against a throwaway database (skipped when PostgreSQL is unreachable)."""

import os
import uuid

import psycopg
import pytest

from srm.build import build

ADMIN_URL = os.environ.get("SRM_ADMIN_URL", "postgresql://srm:srm@localhost:5432/postgres")
TEST_DB = "srm_test"


@pytest.fixture(scope="module")
def conn():
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable")
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {TEST_DB}")
    c = psycopg.connect(ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}")
    report = build(c, verbose=False)
    c.report = report
    yield c
    c.close()
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.close()


def scalar(c, sql, *args):
    return c.execute(sql, args).fetchone()[0]


def test_build_loads_every_family(conn):
    assert len(conn.report) >= 16
    assert all(r["intervals"] > 0 for r in conn.report.values())


def test_second_build_changes_nothing(conn):
    again = build(conn, verbose=False)
    assert all(r["inserted"] == r["updated"] == r["deleted"] == 0 for r in again.values())


def test_as_of_returns_what_was_known_then(conn):
    latest = conn.execute(
        """SELECT a.period_label, a.value FROM obs.as_of('2019-12-31') a
           JOIN obs.series s USING (series_id) WHERE s.family = 'ESTAT:ei_lm_m_vintages'
           ORDER BY a.period DESC LIMIT 1"""
    ).fetchone()
    assert latest[0] == "2019-10"  # November figure was not yet published
    dfr = scalar(
        conn,
        """SELECT a.value FROM obs.as_of('2022-12-31') a JOIN obs.series s USING (series_id)
           WHERE s.family = 'ECB:FM' AND s.series_key LIKE '%%DFR%%' ORDER BY a.period DESC LIMIT 1""",
    )
    assert float(dfr) == 2.0


def test_ingestion_data_is_invisible_to_backtests_by_default(conn):
    n = scalar(
        conn,
        """SELECT count(*) FROM obs.as_of(now()) a JOIN obs.series s USING (series_id)
           WHERE s.knowledge_rule = 'ingestion'""",
    )
    assert n == 0


def test_no_overlapping_knowledge_is_possible(conn):
    sid, period, known_from, snap = conn.execute(
        "SELECT series_id, period, known_from, snapshot_id FROM obs.observation "
        "WHERE known_to IS NOT NULL LIMIT 1"
    ).fetchone()
    with pytest.raises(psycopg.errors.ExclusionViolation), conn.transaction():
        conn.execute(
            """INSERT INTO obs.observation (series_id, period, period_label, value, known_from,
                       known_to, knowledge_precision, snapshot_id)
                   VALUES (%s, %s, 'x', 1, %s + interval '1 second', NULL, 'day', %s)""",
            (sid, period, known_from, snap),
        )


def test_release_rule_cannot_be_declared_for_revised_data(conn):
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
            """INSERT INTO ref.dataset VALUES ('X:bad', 'ecb_hicp', 'X:bad', 'ecb_csv',
                   'release_rule', 'revised', '1 day')"""
        )


def test_llm_claims_cannot_be_accepted_without_reviewer(conn):
    with conn.transaction():
        mv = scalar(
            conn,
            "INSERT INTO model.model_version (label) VALUES (%s) RETURNING model_version_id",
            str(uuid.uuid4()),
        )
        node = scalar(
            conn,
            "INSERT INTO model.node (kind, code, label, definition, model_version_id) "
            "VALUES ('state_variable', %s, 'Inflation', 'HICP', %s) RETURNING node_id",
            str(uuid.uuid4()),
            mv,
        )
        doc = scalar(
            conn,
            "INSERT INTO model.document (doc_key, title, publisher, published_at) "
            "VALUES (%s, 't', 'ECB', now()) RETURNING document_id",
            str(uuid.uuid4()),
        )
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
            """INSERT INTO model.evidence_claim (claim_key, document_id, locator, passage, statement,
                   stance, target_kind, target_key, extracted_by, review_status)
               VALUES (%s, %s, 'p1', 'text', 'claim', 'supports', 'node', 'x', 'llm:any', 'accepted')""",
            (str(uuid.uuid4()), doc),
        )
    assert node


def test_evidence_used_by_an_assessment_cannot_be_deleted(conn):
    with conn.transaction():
        mv = scalar(
            conn,
            "INSERT INTO model.model_version (label) VALUES (%s) RETURNING model_version_id",
            str(uuid.uuid4()),
        )
        node = scalar(
            conn,
            "INSERT INTO model.node (kind, code, label, definition, model_version_id) "
            "VALUES ('regime', %s, 'Higher for longer', 'def', %s) RETURNING node_id",
            str(uuid.uuid4()),
            mv,
        )
        a = scalar(
            conn,
            """INSERT INTO model.assessment (node_id, region_code, as_of, model_version_id,
                   data_quality, evidence_strength, model_confidence, summary)
               VALUES (%s, 'EA', '2022-12-31', %s, 'high', 'medium', 'medium', 'test')
               RETURNING assessment_id""",
            node,
            mv,
        )
        sid, period, kf = conn.execute(
            "SELECT series_id, period, known_from FROM obs.observation LIMIT 1"
        ).fetchone()
        conn.execute(
            """INSERT INTO model.assessment_input (assessment_id, role, series_id, period, known_from)
               VALUES (%s, 'supporting', %s, %s, %s)""",
            (a, sid, period, kf),
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute(
            "DELETE FROM obs.observation WHERE series_id=%s AND period=%s AND known_from=%s",
            (sid, period, kf),
        )


def test_model_content_loaded_with_review_safeguards(conn):
    assert (
        scalar(conn, "SELECT count(*) FROM model.model_version WHERE label LIKE 'phase1-v0.%%'")
        >= 2
    )
    assert (
        scalar(conn, "SELECT count(*) FROM model.edge WHERE evidence_status <> 'hypothesis'") == 0
    )
    assert (
        scalar(conn, "SELECT count(*) FROM model.evidence_claim WHERE review_status = 'accepted'")
        == 0
    )
    assert scalar(conn, "SELECT count(*) FROM model.evidence_claim") >= 30


def test_changed_definitions_require_a_new_model_version(conn):
    from srm.model_content import ModelContentError, sync_model

    conn.execute(
        "UPDATE model.model_version SET definition_sha256 = 'tampered' WHERE label = 'phase1-v0.1'"
    )
    try:
        with pytest.raises(ModelContentError):
            sync_model(conn)
    finally:
        from srm.model_content import MODEL_DIR, definitions_sha256

        conn.execute(
            "UPDATE model.model_version SET definition_sha256 = %s WHERE label = 'phase1-v0.1'",
            (definitions_sha256(MODEL_DIR / "versions" / "phase1-v0.1.yaml"),),
        )


def test_indicators_use_only_data_known_at_the_date(conn):
    from datetime import UTC, datetime

    from srm.indicators import indicator_series, metric

    end_2022 = datetime(2022, 12, 31, 23, tzinfo=UTC)
    assert metric(indicator_series(conn, "ea_policy_rate", end_2022), "level")[0] == 2.0
    assert metric(indicator_series(conn, "ea_hicp_headline_yoy", end_2022), "level")[:2] == (
        10.0,
        "2022-11",
    )
    # Between the end of the RTD core series and today's download no core vintage exists:
    # the indicator is honestly unavailable rather than filled with later knowledge.
    assert indicator_series(conn, "ea_hicp_core_yoy", datetime(2025, 9, 1, tzinfo=UTC)) == []


def test_regime_conditions_at_end_2022(conn):
    from datetime import UTC, datetime

    from srm.regimes import evaluate

    res = evaluate(conn, datetime(2022, 12, 31, 23, tzinfo=UTC))
    hfl = [r for r in res if r.regime == "higher_for_longer" and r.role == "supporting"]
    assert all(r.met for r in hfl)


def test_assessment_run_is_traceable_to_files_and_respects_cutoff(conn):
    from datetime import UTC, datetime

    from srm.assess import assess, persist
    from srm.build import REPO
    from srm.report import load_run, render_html, render_markdown

    at = datetime(2022, 12, 31, 23, tzinfo=UTC)
    run = load_run(conn, persist(conn, assess(conn, at)))
    assert {r["code"] for r in run["regimes"]} == {"higher_for_longer", "recession_disinflation"}
    for r in run["regimes"]:
        assert r["observations"], r["code"]
        assert all((REPO / o["path"]).exists() for o in r["observations"])
        assert all(o["known_from"] <= at for o in r["observations"])
        assert all(c["published_at"] <= at for c in r["claims"])
    assert "<title>Euro Area Regime Monitor</title>" in render_html([run])
    assert "Trace to source files" in render_markdown(run)


def test_both_model_versions_stay_reproducible(conn):
    from datetime import UTC, datetime

    from srm.assess import assess

    at = datetime(2024, 12, 31, 23, tzinfo=UTC)
    ids = dict(conn.execute("SELECT label, model_version_id FROM model.model_version").fetchall())
    v1 = {r.code: r.position for r in assess(conn, at, ids["phase1-v0.1"])["regimes"]}
    v2 = {r.code: r.position for r in assess(conn, at, ids["phase1-v0.2"])["regimes"]}
    assert v1["higher_for_longer"] == "strongly supported"
    assert v2["higher_for_longer"] == "supported"  # the 2024 easing now counts against it


def test_fresh_components_extend_recent_months_without_touching_the_past(conn):
    from datetime import UTC, datetime

    from srm.indicators import indicator_series, metric

    past = datetime(2024, 12, 31, 23, tzinfo=UTC)
    now = datetime.now(UTC)
    assert metric(indicator_series(conn, "ea_hicp_headline_yoy", past), "level")[1] == "2024-11"
    latest_now = metric(indicator_series(conn, "ea_hicp_headline_yoy", now), "level")[1]
    assert latest_now >= "2026-09"  # RTD ends 2026-08; the HICP extension adds later months
    assert metric(indicator_series(conn, "ea_ulc_yoy", past), "level")[1] == "2024-Q1"
    assert metric(indicator_series(conn, "ea_ulc_yoy", now), "level")[1] >= "2026-Q2"
