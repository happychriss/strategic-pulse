# Model content and review

Model content lives in git, versioned:

| File | Contents | Rule |
|---|---|---|
| `model/versions/<label>.yaml` | Nodes (axes, state variables, regimes), indicators, relationships, regime conditions | Frozen once loaded; a change needs a new file and label (build enforces). All versions stay loaded so older assessments remain reproducible |
| `model/current.yaml` | Names the version used for new assessments | |
| `model/documents.yaml` | Cited documents; `published_on` equals the page's own metadata (tested) | Knowledge time = end of that day |
| `model/claims.yaml` | Evidence claims with verbatim passages | Build fails if a passage is not in the archived document |

`python scripts/pull_documents.py` archives any newly listed document.

## Phase 1 content (phase1-v0.1, phase1-v0.2)

- **Axes:** Resources/Energy, Fiscal Capacity.
- **State variables:** headline and underlying inflation, unit labour costs, policy rate,
  long-term financing costs, unemployment, output growth.
- **Regimes:** higher for longer; recession/disinflation. Each has supporting and opposing
  conditions on indicator metrics.
- **Relationships:** 8 mechanisms plus 4 links to regimes. 32 claims from 9 ECB documents,
  covering supports, qualifies and contradicts.

## Why everything is still a hypothesis

The claims were selected and extracted with AI assistance. Concept requirement 9 says AI
output must not silently become accepted evidence, and the database enforces it: an
`llm:` claim cannot be `accepted` without `reviewed_by`. So:

- all 32 claims are `proposed`;
- all relationships are `hypothesis`; `proposed_status` shows what the evidence would support.

### How to review

1. Read each claim's passage in context: open the archived page under
   `data/raw/documents/<doc>/` or the URL in `model/documents.yaml`.
2. In `model/claims.yaml` set `review_status: accepted` or `rejected` and
   `reviewed_by: <your name>`. Edit `statement` if the summary overreaches.
3. When a relationship has accepted supporting evidence you agree with, set its `status` to the
   `proposed_status` in a **new model version**: copy the current file in `model/versions/` to a new
   label, edit it there, and point `model/current.yaml` at it.
4. Run `python -m srm.build` and `pytest`. Tests refuse a promoted relationship without an
   accepted supporting claim.

## Findings from the first evaluation

Conditions evaluated as of end-2019, end-2021, end-2022, end-2024 and today:

| As of | Higher for longer (supporting met) | Recession/disinflation (supporting met) |
|---|---|---|
| 2019-12-31 | 1 of 4 | 1 of 4 |
| 2021-12-31 | 3 of 4 | 0 of 4 |
| 2022-12-31 | 4 of 4 | 0 of 4 |
| 2024-12-31 | 4 of 4 | 1 of 4 |
| 2026-10-03 | 3 of 4 | 0 of 4 |

- **The move into higher for longer shows up.** By end-2022 all four signals were met.
- **The 2024 easing does not show up.** At end-2024 all four signals were still met while the
  ECB was cutting, because the conditions use levels and underlying inflation (2.76%) was
  above 2.5%. Candidate fix for v0.2: treat policy easing (`change_6m < 0`) as opposing
  evidence. This is a model change and should be decided, not tuned after the fact.
- **Underlying inflation has a vintage gap.** The RTD core series ends in May 2025; the new HICP
  dataset has only retrieval-time knowledge. Between July 2025 and the first download the
  indicator is unavailable as of those dates.
- **Unit labour costs are stale.** OECD data for the euro area ends in 2024-Q1 in all editions.

## phase1-v0.2 and the assessment page

v0.2 adds one opposing condition to higher for longer: the deposit rate lower than six months
earlier. Both versions remain loaded; tests prove each still gives its own answer.

| As of | v0.1 higher for longer | v0.2 higher for longer | v0.2 recession/disinflation |
|---|---|---|---|
| 2019-12-31 | mixed | mixed | not supported |
| 2021-12-31 | strongly supported | strongly supported | not supported |
| 2022-12-31 | strongly supported | strongly supported | not supported |
| 2024-12-31 | strongly supported | supported | not supported |
| 2026-10-03 | supported (3 of 4) | strongly supported | not supported |

- **The easing now registers at end-2024** as one opposing condition, lowering the position to
  supported.
- **The six-month direction at end-2024 still reads strongly increasing.** In mid-2024 underlying
  inflation had fallen 1.3 points in six months (opposing condition met, position mixed); by
  end-2024 it had stalled at 2.76%. The rebound is a real feature of late 2024, but the cutoffs are
  too far apart to show the mid-2024 dip. Monthly cutoffs would.
- **Evidence strength reads low everywhere** because no claim has been reviewed yet.

Regenerate the pages with `python -m srm.assess` (defaults to the four Phase 1 dates and now).
Each run is stored in `model.assessment_run`; every judgement links to its observations, claims
and driving relationships in `model.assessment_input`. Pages are written to
`reports/assessments/<version>/`: one Markdown file per cutoff and `index.html` for all cutoffs.
The rules are documented at the top of `src/srm/assess.py` (`ENGINE_VERSION`).
