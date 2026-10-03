# Model content and review

Model content lives in git, versioned:

| File | Contents | Rule |
|---|---|---|
| `model/model.yaml` | Nodes (axes, state variables, regimes), indicators, relationships, regime conditions | Immutable per `model_version.label`; any change needs a new label (build enforces) |
| `model/documents.yaml` | Cited documents; `published_on` equals the page's own metadata (tested) | Knowledge time = end of that day |
| `model/claims.yaml` | Evidence claims with verbatim passages | Build fails if a passage is not in the archived document |

`python scripts/pull_documents.py` archives any newly listed document.

## Phase 1 content (phase1-v0.1)

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
   `proposed_status` in a **new model version** (change `model_version.label`, e.g. `phase1-v0.2`).
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
