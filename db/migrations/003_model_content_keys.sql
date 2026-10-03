-- 003: keys that tie model rows to the versioned YAML files in model/, regime conditions,
-- and proposed evidence status for review.

-- Definitions are immutable per model version; the same code may exist in several versions.
ALTER TABLE model.node DROP CONSTRAINT node_code_key;
ALTER TABLE model.node ADD CONSTRAINT node_code_per_version UNIQUE (code, model_version_id);
ALTER TABLE model.indicator DROP CONSTRAINT indicator_code_key;
ALTER TABLE model.indicator ADD CONSTRAINT indicator_code_per_version UNIQUE (code, model_version_id);

ALTER TABLE model.edge ADD COLUMN edge_key text NOT NULL;
ALTER TABLE model.edge ADD CONSTRAINT edge_key_per_version UNIQUE (edge_key, model_version_id);
-- Requirement 9: a relationship proposed with AI help stays a hypothesis until a person
-- reviews its evidence; the proposed status is kept separately for that review.
ALTER TABLE model.edge ADD COLUMN proposed_evidence_status model.evidence_status;

ALTER TABLE model.document ADD COLUMN doc_key text NOT NULL;
ALTER TABLE model.document ADD CONSTRAINT document_doc_key UNIQUE (doc_key);

-- Claims are evidence and outlive model versions, so they name their target by key.
ALTER TABLE model.evidence_claim DROP COLUMN edge_id;
ALTER TABLE model.evidence_claim DROP COLUMN node_id;
ALTER TABLE model.evidence_claim ADD COLUMN claim_key text NOT NULL;
ALTER TABLE model.evidence_claim ADD CONSTRAINT evidence_claim_key UNIQUE (claim_key);
ALTER TABLE model.evidence_claim ADD COLUMN target_kind text NOT NULL CHECK (target_kind IN ('edge', 'node'));
ALTER TABLE model.evidence_claim ADD COLUMN target_key text NOT NULL;

-- Observable signature of a regime: conditions on indicator metrics, versioned with the model.
CREATE TABLE model.regime_condition (
    condition_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id int NOT NULL REFERENCES model.model_version,
    condition_key    text NOT NULL,
    regime_node      uuid NOT NULL REFERENCES model.node,
    indicator_id     uuid NOT NULL REFERENCES model.indicator,
    metric           text NOT NULL CHECK (metric IN ('level', 'change_3m', 'change_6m', 'change_12m')),
    comparator       text NOT NULL CHECK (comparator IN ('>', '>=', '<', '<=')),
    threshold        numeric NOT NULL,
    role             text NOT NULL CHECK (role IN ('supporting', 'opposing')),
    rationale        text NOT NULL,
    UNIQUE (condition_key, model_version_id)
);

COMMENT ON FUNCTION obs.as_of(timestamptz, boolean) IS
  'Values knowable at p_at. Ingestion-time rows can never appear before their retrieval time, '
  'so including them leaks nothing; they are excluded by default only to keep the source mix '
  'comparable across backtest dates. Pass true where they are the only source.';
