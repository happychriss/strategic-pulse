-- 002: model layer. Kept relational and graph-shaped (node/edge) so it can be loaded
-- into Apache AGE later without redesign. Nothing here is populated by code yet:
-- relationships and regimes are entered by hand with evidence (Phase 1).

CREATE SCHEMA model;

CREATE TYPE model.level AS ENUM ('low', 'medium', 'high');
CREATE TYPE model.node_kind AS ENUM ('structural_axis', 'state_variable', 'regime', 'scenario');
CREATE TYPE model.semantics AS ENUM ('higher_is_toward_high_pole', 'higher_is_toward_low_pole', 'neutral');
CREATE TYPE model.rel_type AS ENUM ('contributes_to', 'counteracts', 'supports', 'weakens', 'transmits_to', 'influences');
-- Requirement 3: observation, correlation, mechanism and causality are never conflated.
CREATE TYPE model.evidence_status AS ENUM (
    'hypothesis', 'observed_correlation', 'supported_mechanism', 'causal_evidence', 'contradicted');
CREATE TYPE model.stance AS ENUM ('supports', 'contradicts', 'qualifies');
CREATE TYPE model.review_status AS ENUM ('proposed', 'accepted', 'rejected');
CREATE TYPE model.direction AS ENUM (
    'strongly_increasing', 'increasing', 'broadly_stable', 'decreasing', 'strongly_decreasing');

-- Requirement 7: every definition belongs to a model version ("our model changed").
CREATE TABLE model.model_version (
    model_version_id  serial PRIMARY KEY,
    label             text NOT NULL UNIQUE,
    created_at        timestamptz NOT NULL DEFAULT now(),
    definition_sha256 text,
    notes             text
);

CREATE TABLE model.node (
    node_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind             model.node_kind NOT NULL,
    code             text NOT NULL UNIQUE,
    label            text NOT NULL,
    definition       text NOT NULL,
    low_pole         text,
    high_pole        text,
    model_version_id int NOT NULL REFERENCES model.model_version
);

CREATE TABLE model.indicator (
    indicator_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code             text NOT NULL UNIQUE,
    label            text NOT NULL,
    node_id          uuid NOT NULL REFERENCES model.node,
    region_code      text NOT NULL REFERENCES ref.region,
    unit             text,
    semantics        model.semantics NOT NULL,
    definition       text NOT NULL,
    model_version_id int NOT NULL REFERENCES model.model_version
);

-- Which series feeds an indicator, and during which knowledge window. Splices become
-- explicit data, e.g. OECD EA19 editions before 2023-04, EA20 editions after.
CREATE TABLE model.indicator_component (
    indicator_id uuid NOT NULL REFERENCES model.indicator ON DELETE CASCADE,
    role         text NOT NULL DEFAULT 'value',      -- e.g. value, minuend, subtrahend
    series_id    uuid NOT NULL REFERENCES obs.series,
    serves       tstzrange NOT NULL DEFAULT '(,)',
    transform    text NOT NULL DEFAULT 'identity',  -- documented, versioned transformation
    note         text,
    PRIMARY KEY (indicator_id, role, series_id, serves),
    CONSTRAINT one_series_per_role_and_instant
        EXCLUDE USING gist (indicator_id WITH =, role WITH =, serves WITH &&)
);

CREATE TABLE model.edge (
    edge_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    src_node         uuid NOT NULL REFERENCES model.node,
    dst_node         uuid NOT NULL REFERENCES model.node,
    rel_type         model.rel_type NOT NULL,
    expected_sign    smallint CHECK (expected_sign IN (-1, 0, 1)),
    lag_min          interval,
    lag_max          interval,
    region_code      text REFERENCES ref.region,     -- NULL = general mechanism
    valid            daterange NOT NULL DEFAULT '(,)',
    evidence_status  model.evidence_status NOT NULL DEFAULT 'hypothesis',
    confidence       model.level,
    model_version_id int NOT NULL REFERENCES model.model_version,
    reviewed_on      date,
    note             text,
    CHECK (src_node <> dst_node),
    CHECK (lag_min IS NULL OR lag_max IS NULL OR lag_min <= lag_max)
);

CREATE TABLE model.document (
    document_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title        text NOT NULL,
    publisher    text NOT NULL,
    url          text,
    published_at timestamptz NOT NULL,   -- knowledge time of the document
    sha256       text,
    local_path   text
);

CREATE TABLE model.evidence_claim (
    claim_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   uuid NOT NULL REFERENCES model.document,
    locator       text NOT NULL,          -- page, section, box
    passage       text NOT NULL,          -- verbatim source text
    statement     text NOT NULL,          -- the structured claim
    stance        model.stance NOT NULL,  -- requirement 4: counter-evidence is first-class
    edge_id       uuid REFERENCES model.edge,
    node_id       uuid REFERENCES model.node,
    region_code   text REFERENCES ref.region,
    strength      model.level,
    extracted_by  text NOT NULL,          -- 'human' or 'llm:<model>'
    review_status model.review_status NOT NULL DEFAULT 'proposed',
    reviewed_by   text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(edge_id, node_id) = 1),
    -- Requirement 9: AI output never becomes accepted evidence without a human reviewer.
    CONSTRAINT llm_claims_need_review CHECK (
        review_status <> 'accepted' OR extracted_by = 'human' OR reviewed_by IS NOT NULL)
);

CREATE TABLE model.assessment (
    assessment_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id          uuid REFERENCES model.node,
    edge_id          uuid REFERENCES model.edge,
    region_code      text NOT NULL REFERENCES ref.region,
    as_of            timestamptz NOT NULL,   -- knowledge cutoff: only data known then is used
    model_version_id int NOT NULL REFERENCES model.model_version,
    position         text,
    direction        model.direction,
    velocity         model.level,
    acceleration     text CHECK (acceleration IN ('strengthening', 'weakening', 'none')),
    edge_state       text CHECK (edge_state IN (
                         'active', 'strengthening', 'weakening', 'conditional', 'unsupported', 'contradicted')),
    -- Requirement 6: three separate uncertainty dimensions, never one score.
    data_quality      model.level NOT NULL,
    evidence_strength model.level NOT NULL,
    model_confidence  model.level NOT NULL,
    summary           text NOT NULL,
    would_change_view text,                  -- falsification criteria
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(node_id, edge_id) = 1),
    CHECK (edge_state IS NULL OR edge_id IS NOT NULL)
);

-- Provenance (W3C PROV "wasDerivedFrom"). Observation references use the natural key,
-- which is stable across rebuilds; RESTRICT stops deletion of evidence that was used.
CREATE TABLE model.assessment_input (
    assessment_id       uuid NOT NULL REFERENCES model.assessment ON DELETE CASCADE,
    role                text NOT NULL CHECK (role IN ('supporting', 'contradicting', 'context')),
    series_id           uuid,
    period              daterange,
    known_from          timestamptz,
    claim_id            uuid REFERENCES model.evidence_claim,
    input_assessment_id uuid REFERENCES model.assessment,
    indicator_id        uuid REFERENCES model.indicator,
    note                text,
    FOREIGN KEY (series_id, period, known_from)
        REFERENCES obs.observation (series_id, period, known_from) ON DELETE RESTRICT,
    CHECK (num_nonnulls(series_id, claim_id, input_assessment_id, indicator_id) = 1),
    CHECK ((series_id IS NULL) = (period IS NULL) AND (series_id IS NULL) = (known_from IS NULL))
);
CREATE INDEX assessment_input_by_assessment ON model.assessment_input (assessment_id);
