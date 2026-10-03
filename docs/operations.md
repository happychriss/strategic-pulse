# Operations: the monthly run

The system refreshes on demand: a person starts the run, either locally or by firing the Claude
Code routine by hand ("Run now"). The routine has no schedule for now. When it runs it starts a
fresh cloud session, checks out `main`, runs the pipeline, and reports. It checks out `main`
itself because the repository's default branch is set in GitHub settings. A monthly schedule can
be added later in the routine settings without changing anything here.

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
5. **Write** pages to `reports/assessments/<version>/`, the newsletter dashboard to
   `reports/dashboard/index.html` (with its data in `data.json`), and a run log to
   `reports/runs/<date>.md` and `.json`. The log lists what changed since the previous run log.

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

1. Make sure you are on main: if the repository is not checked out, clone it; then
   git fetch origin main && git checkout -B monthly/<YYYY-MM-DD> origin/main.
   (The repository's default branch may not be main, so do not rely on the initial checkout.)
   Then set up: CLAUDE_CODE_REMOTE=true CLAUDE_PROJECT_DIR=$PWD .claude/hooks/session-start.sh
   This installs dependencies, starts PostgreSQL and builds the database. Read docs/operations.md.
2. Run: PYTHONPATH=src .venv/bin/python -m srm.run_monthly
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
   reports/assessments/<current version>/index.html to that url. Then Artifact read
   https://claude.ai/artifact/RRKNrEVKPnb3oqzxoaWqvQ and publish reports/dashboard/index.html
   to that url (the newsletter dashboard "Lagebild Europa").
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

## Change detector

`python -m srm.detect` runs the detector for now and the historical test 2008 to today, writing
`reports/detector/<version>.md`. The monthly run includes the current detection in its run log
under "Is something happening?". Settings live in the `detector` section of the model version:
`sensitivity` (unusual = larger than this share of the signal's own past 3-month changes) and
`alarm_layers` (layers needed for an alarm). Reference events for the test are in
`model/events.yaml` and must be fixed before a run, never adjusted to results.

### Model phase1-v0.5

- **Direction lens:** a 6-month change that flips sign after at least 75% of the previous 12
  months moved the other way, and exceeds the median of the signal's own 6-month moves.
- **New versus ongoing alarms:** a new alarm needs `onset_quiet_months` (3) quiet months before.
- **Yearly structural layer** (`srm.structural`): 11 indicators across all nine axes for the 27
  member states. Five-year trend against the previous five years; a Europe-wide movement is
  flagged when unusually many member states change trend the same way (at least three). The
  EU aggregate alone is never tested against single countries, because averages move less.
- `python -m srm.detect` writes `reports/detector/<version>.md` (test) and `.json` (page data);
  the monthly run and `python -m srm.assess` both refresh them before writing the page.

## Newsletter dashboard ("Lagebild Europa")

`python -m srm.dashboard` writes `reports/dashboard/index.html`, a German one-page view of the
current situation, meant to accompany the strategic newsletter. It is built only from the
detector result (`reports/detector/<version>.json`) and the database, and it adds nothing of its
own: no thresholds, no wording that the data does not support.

- **Top:** the status sentence (quiet, one layer moving, several layers moving), the signals
  behind it, and the last four months.
- **Monthly:** each of the six layers with its signals, ten years of history, and a bar that
  measures the latest three-month move against the signal's own past moves (the tick is the 95th
  percentile).
- **Record since 2008:** the monthly level with the reference events and the back-test score.
- **Slow trends:** the eleven yearly indicators, EU value with the fitted trend of the last five
  years against the five before, and the breadth of member states with unusual trend changes.
- **Sources:** every card used, dataset codes that delivered data, licence and retrieval date.
  Each number on the page carries its own source line.

The published page is private until shared from the page's Share menu. Readers outside the
account need a public link.
