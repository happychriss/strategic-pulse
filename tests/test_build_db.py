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
            "INSERT INTO model.document (title, publisher, published_at) VALUES ('t', 'ECB', now()) "
            "RETURNING document_id",
        )
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
            """INSERT INTO model.evidence_claim (document_id, locator, passage, statement, stance,
                   node_id, extracted_by, review_status)
               VALUES (%s, 'p1', 'text', 'claim', 'supports', %s, 'llm:any', 'accepted')""",
            (doc, node),
        )


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
