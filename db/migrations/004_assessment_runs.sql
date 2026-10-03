-- 004: group assessments into runs (one run = one as-of instant, model version and region)
-- and keep the structured payload the assessment page renders.

CREATE TABLE model.assessment_run (
    run_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    as_of            timestamptz NOT NULL,
    model_version_id int NOT NULL REFERENCES model.model_version,
    region_code      text NOT NULL REFERENCES ref.region,
    engine_version   text NOT NULL,   -- assessment rules version (see srm.assess.ENGINE_VERSION)
    created_at       timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE model.assessment ADD COLUMN run_id uuid REFERENCES model.assessment_run ON DELETE CASCADE;
ALTER TABLE model.assessment ADD COLUMN details jsonb;
CREATE INDEX assessment_by_run ON model.assessment (run_id);
