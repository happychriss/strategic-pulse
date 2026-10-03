# Operations: the monthly run

The system refreshes itself once a month through a Claude Code routine: a scheduled job that
starts a fresh cloud session on the default branch (`main`), runs the pipeline, and reports.

## What one run does

```bash
python -m srm.run_monthly
```

1. **Pull** every manifest entry again (`srm.pull`). A snapshot is archived only when its
   content changed; identical downloads are discarded. Retrieval-time sources accumulate their
   own vintage history this way, one snapshot per month.
2. **Build** the database from cards, snapshots and model files (`srm.build`).
3. **Test** (`pytest`). On failure the run stops: no pages, no run log.
4. **Assess** the four Phase 1 cutoffs and now with the current model version (`srm.assess`).
5. **Write** pages to `reports/assessments/<version>/` and a run log to `reports/runs/<date>.md`
   and `.json`. The log lists what changed since the previous run log.

Exit codes: `0` all good, `2` some pulls failed (everything else ran), `1` tests failed or the
pipeline broke.

## Guardrails for the routine

| The routine may | The routine may not |
|---|---|
| pull, build, test, assess, write pages and run logs | edit `model/`, thresholds, model versions or claim reviews |
| commit `data/raw/**` and `reports/**`, open a pull request and merge it when checks pass | merge anything that touches other paths |
| republish the assessment page | change source cards' dataset rules or migrations |
| propose a code fix in a separate pull request left open for review | accept its own proposed fixes |

Methodology stays a human decision: "the world changed" is automated, "our model changed" is not.

## Routine prompt (stored in the routine; keep in sync)

```text
Monthly run of the Strategic Regime Monitor (repository happychriss/strategic-pulse).

1. Read docs/operations.md. Work on the branch this session is assigned; if none, create
   monthly/<YYYY-MM-DD> from main.
2. Run: PYTHONPATH=src .venv/bin/python -m srm.run_monthly   (the session-start hook has already
   installed dependencies, started PostgreSQL and built the database).
3. If this message contains "DRY RUN": stop after step 2. Do not commit, push, open or merge pull
   requests, or publish. Report the run log (reports/runs/<date>.md), the exit code, which files
   would be committed, and anything that looked wrong.
4. Exit code 0 or 2: commit only data/raw/** and reports/**. Open a pull request to main titled
   "Monthly run <date>" with the run log as its body. Merge it only if the exit code was 0 or 2,
   the tests passed, and every changed file is under data/raw/ or reports/. Otherwise leave it open
   and say why.
5. Exit code 1: commit nothing to main. Open a pull request or issue with the failing output.
6. Never edit model/, sources/ dataset rules, claim review fields or db/migrations/ in this run.
   If code needs fixing (for example an API changed), open a separate pull request with the
   proposed fix and leave it for human review.
7. After a merge, republish the assessment page: Artifact read
   https://claude.ai/artifact/5pxWmri8Cw7mgwnPV4TzoV, then publish
   reports/assessments/<current version>/index.html to that url.
8. Finish with a short summary: what changed (from the run log), regime positions, failures,
   and links to the pull request and the page.
```

## Running it by hand

```bash
PYTHONPATH=src .venv/bin/python -m srm.run_monthly            # full run
PYTHONPATH=src .venv/bin/python -m srm.run_monthly --no-pull  # rebuild and reassess only
PYTHONPATH=src .venv/bin/python -m srm.pull --missing-only    # fetch never-archived entries
```

## Known recurring failures

- Eurostat `ei_is_m_vtgfix` (industrial production vintages 2001-2020) exceeds the size cap;
  not in the manifest until chunked requests exist.
- ECB RTD industrial production history times out; removed from the manifest.
- ENTSO-E needs an API token (`ENTSOE_API_TOKEN`); not in the manifest.
