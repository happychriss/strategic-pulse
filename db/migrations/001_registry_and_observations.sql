-- 001: registry, raw snapshot archive, bitemporal observations.
--
-- Valid time     = obs.observation.period   (the real-world period a value describes)
-- Knowledge time = obs.observation.known    (when the value was knowable, never earlier)
--
-- PostgreSQL 16 has no native WITHOUT OVERLAPS; btree_gist exclusion constraints give
-- the same guarantee: one value per series, period and instant of knowledge.

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA ref;   -- registry: source cards, datasets, regions
CREATE SCHEMA raw;   -- archive of upstream files (the durable layer lives in git)
CREATE SCHEMA obs;   -- observations rebuilt from raw snapshots

-- ---------------------------------------------------------------- registry
CREATE TYPE ref.knowledge_rule AS ENUM (
    'source_vintage_log',  -- change log with exact timestamps (ECB RTD includeHistory)
    'revdate_dimension',   -- vintage table with revision-date dimension (Eurostat)
    'edition_dimension',   -- monthly database editions (OECD)
    'release_rule',        -- unrevised data: known at period end + release lag
    'ingestion'            -- revised data without vintages: known only from retrieval
);
CREATE TYPE ref.revision_class AS ENUM ('revised', 'unrevised');

CREATE TABLE ref.source_card (
    card_id             text PRIMARY KEY,
    provider            text NOT NULL,
    name                text NOT NULL,
    role                text NOT NULL,
    phase               smallint NOT NULL CHECK (phase BETWEEN 1 AND 3),
    vintage_support     text NOT NULL,
    verification_status text NOT NULL CHECK (verification_status IN ('unverified', 'verified')),
    superseded_by       text REFERENCES ref.source_card DEFERRABLE INITIALLY DEFERRED,
    card                jsonb NOT NULL,      -- full YAML card, for audit
    card_sha256         text NOT NULL,
    synced_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ref.dataset (
    dataset_id     text PRIMARY KEY CHECK (dataset_id LIKE '%:%'),  -- e.g. ECB:RTD, ESTAT:ei_lm_m_vtg
    card_id        text NOT NULL REFERENCES ref.source_card,
    family         text NOT NULL,  -- series identity scope; split vintage tables share one family
    parser         text NOT NULL,
    knowledge_rule ref.knowledge_rule NOT NULL,
    revision_class ref.revision_class NOT NULL,
    release_lag    interval,
    -- Safety rule: only unrevised data may claim knowledge before retrieval via a release rule.
    CONSTRAINT release_rule_only_for_unrevised CHECK (
        knowledge_rule <> 'release_rule'
        OR (revision_class = 'unrevised' AND release_lag IS NOT NULL)
    )
);

CREATE TABLE ref.region (
    code        text PRIMARY KEY,
    label       text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('country', 'monetary_union', 'economic_union')),
    composition text NOT NULL CHECK (composition IN ('fixed', 'changing', 'n/a')),
    note        text
);

-- Source systems name the same region differently (ECB U2/S0, Eurostat EA, OECD EA19/EA20).
CREATE TABLE ref.region_alias (
    system      text NOT NULL,
    source_code text NOT NULL,
    region_code text NOT NULL REFERENCES ref.region,
    note        text,
    PRIMARY KEY (system, source_code)
);

INSERT INTO ref.region (code, label, kind, composition, note) VALUES
  ('EA',        'Euro area (changing composition)', 'monetary_union', 'changing', 'Official evolving aggregate: EA11 1999 ... EA20 2023, EA21 2026'),
  ('EA19',      'Euro area, 19 countries',          'monetary_union', 'fixed', 'Fixed composition, back-cast'),
  ('EA20',      'Euro area, 20 countries',          'monetary_union', 'fixed', 'Fixed composition, back-cast'),
  ('EA21',      'Euro area, 21 countries',          'monetary_union', 'fixed', 'Fixed composition from 2026, back-cast'),
  ('EU27_2020', 'European Union, 27 countries (from 2020)', 'economic_union', 'fixed', NULL),
  ('DE', 'Germany', 'country', 'n/a', NULL),
  ('FR', 'France',  'country', 'n/a', NULL),
  ('IT', 'Italy',   'country', 'n/a', NULL),
  ('ES', 'Spain',   'country', 'n/a', NULL),
  ('US', 'United States', 'country', 'n/a', NULL),
  ('JP', 'Japan',   'country', 'n/a', NULL);

INSERT INTO ref.region_alias (system, source_code, region_code, note) VALUES
  ('ECB',   'U2',        'EA',        'ECB code for euro area, changing composition'),
  ('ECB',   'S0',        'EA',        'ECB RTD code for euro area'),
  ('ECB',   'US',        'US',        NULL),
  ('ECB',   'JP',        'JP',        NULL),
  ('ESTAT', 'EA',        'EA',        NULL),
  ('ESTAT', 'EA19',      'EA19',      NULL),
  ('ESTAT', 'EA20',      'EA20',      NULL),
  ('ESTAT', 'EA21',      'EA21',      NULL),
  ('ESTAT', 'EU27_2020', 'EU27_2020', NULL),
  ('ESTAT', 'DE', 'DE', NULL), ('ESTAT', 'FR', 'FR', NULL),
  ('ESTAT', 'IT', 'IT', NULL), ('ESTAT', 'ES', 'ES', NULL),
  ('OECD',  'EA19',      'EA19',      'Used for editions 2015-03 to 2023-03'),
  ('OECD',  'EA20',      'EA20',      'Used for editions from 2023-04');

-- ---------------------------------------------------------------- raw archive
CREATE TABLE raw.snapshot (
    snapshot_id  uuid PRIMARY KEY,            -- md5(path)::uuid, stable across rebuilds
    card_id      text NOT NULL REFERENCES ref.source_card,
    dataset_id   text REFERENCES ref.dataset, -- NULL when the URL maps to no declared dataset
    label        text NOT NULL,
    path         text NOT NULL UNIQUE,        -- relative to repository root
    url          text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    sha256       text NOT NULL,
    bytes        bigint NOT NULL,
    compression  text,
    load_status  text NOT NULL DEFAULT 'pending'
                 CHECK (load_status IN ('pending', 'loaded', 'skipped', 'failed')),
    load_note    text
);

-- ---------------------------------------------------------------- observations
CREATE TYPE obs.knowledge_precision AS ENUM ('minute', 'day', 'month', 'release_rule', 'retrieval');

CREATE TABLE obs.series (
    series_id      uuid PRIMARY KEY,          -- md5(family || '|' || series_key)::uuid
    family         text NOT NULL,
    series_key     text NOT NULL,             -- canonical dimension key without time/vintage
    dims           jsonb NOT NULL,
    region_code    text REFERENCES ref.region,
    freq           text,
    unit           text,
    title          text,
    knowledge_rule ref.knowledge_rule NOT NULL,
    UNIQUE (family, series_key)
);

CREATE TABLE obs.observation (
    series_id    uuid NOT NULL REFERENCES obs.series ON DELETE RESTRICT,
    period       daterange NOT NULL
                 CHECK (NOT isempty(period) AND lower_inc(period) AND NOT upper_inc(period)
                        AND NOT lower_inf(period) AND NOT upper_inf(period)),
    period_label text NOT NULL,               -- as published, e.g. 2026-Q2, 2025-S2
    value        numeric NOT NULL,            -- exact decimal as published
    obs_status   text,                        -- source flag, e.g. A, p, e
    attrs        jsonb,                       -- attributes that can change by vintage (base period ...)
    known_from   timestamptz NOT NULL,
    known_to     timestamptz,                 -- NULL = still the latest known value
    known        tstzrange GENERATED ALWAYS AS (tstzrange(known_from, known_to, '[)')) STORED,
    knowledge_precision obs.knowledge_precision NOT NULL,
    snapshot_id  uuid NOT NULL REFERENCES raw.snapshot,  -- provenance: file that first showed it
    PRIMARY KEY (series_id, period, known_from),
    CHECK (known_to IS NULL OR known_to > known_from),
    CONSTRAINT one_value_per_instant
        EXCLUDE USING gist (series_id WITH =, period WITH =, known WITH &&)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX observation_known_gist ON obs.observation USING gist (known);
CREATE INDEX observation_snapshot ON obs.observation (snapshot_id);

-- What was knowable at instant p_at. Ingestion-time data is excluded by default because
-- its true publication time is unknown; including it would leak revisions into backtests.
CREATE FUNCTION obs.as_of(p_at timestamptz, p_include_ingestion boolean DEFAULT false)
RETURNS TABLE (
    series_id uuid, period daterange, period_label text, value numeric,
    known_from timestamptz, knowledge_rule ref.knowledge_rule, snapshot_id uuid
)
LANGUAGE sql STABLE AS $$
    SELECT o.series_id, o.period, o.period_label, o.value, o.known_from, s.knowledge_rule, o.snapshot_id
    FROM obs.observation o
    JOIN obs.series s USING (series_id)
    WHERE o.known @> p_at
      AND (p_include_ingestion OR s.knowledge_rule <> 'ingestion')
$$;

CREATE VIEW obs.current AS
    SELECT * FROM obs.observation WHERE known_to IS NULL;

-- First published value per period: the basis for revision analysis.
CREATE VIEW obs.first_release AS
    SELECT DISTINCT ON (series_id, period) *
    FROM obs.observation
    ORDER BY series_id, period, known_from;
