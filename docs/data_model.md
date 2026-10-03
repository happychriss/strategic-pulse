# Data model

PostgreSQL 16. Plain relational schema, no Apache AGE or pgvector yet (see
`docs/research/00_grounding_assessment.md`, section 5). Migrations live in `db/migrations`
and are immutable once applied.

## Layers

| Schema | Holds | Filled by |
|---|---|---|
| `ref` | Source cards, datasets, regions and region aliases | `srm.build` from `sources/*.yaml` |
| `raw` | Registry of archived upstream files | `srm.build` from `data/raw/**/*.meta.json` |
| `obs` | Series and bitemporal observations | `srm.build` from raw snapshots |
| `model` | Model versions, nodes, indicators, edges, documents, claims, assessments | By hand, with evidence (Phase 1) |

The durable layer is the raw snapshot archive in git. The database is always rebuildable
from it: `python -m srm.build`. The session-start hook does this automatically.

## Two time axes

- **Valid time** is `obs.observation.period`, a half-open date range for the period the
  value describes (`2026-Q2` becomes `[2026-04-01, 2026-07-01)`).
- **Knowledge time** is `obs.observation.known`, a half-open timestamp range during which
  this value was the latest published one. `known_to` is NULL while it still is.

An exclusion constraint (`btree_gist`) guarantees one value per series, period and instant.
This is the PostgreSQL 16 equivalent of PG18 `WITHOUT OVERLAPS`.

## Knowledge rules

Each dataset declares how knowledge time is derived. Every rule errs late, so a backtest
can miss a value that was public slightly earlier but can never see one too early.

| Rule | Used by | Knowledge starts | Precision |
|---|---|---|---|
| `source_vintage_log` | ECB RTD | `VALID_FROM` timestamp in the source | minute |
| `revdate_dimension` | Eurostat vintage tables | end of the revision date | day |
| `edition_dimension` | OECD revisions database | first day of the month after the edition | month |
| `release_rule` | ECB policy rates, yield curve | end of period plus declared lag | rule |
| `ingestion` | all other revised data | retrieval time of the snapshot | retrieval |

Rules enforced in the database and in the card validator:

- `release_rule` is only allowed for `unrevised` data. A release date says nothing about later
  revisions.
- `obs.as_of(at)` excludes `ingestion` data unless asked. Its real publication time is
  unknown, so including it would leak revisions into backtests.

## Vintages become intervals

Sources publish vintages in different shapes. The build turns each into publication
events per series and period, then collapses them (`srm.knowledge.collapse`):

- identical consecutive publications merge into one interval;
- a changed value closes the old interval and opens a new one;
- a withdrawal (ECB `Delete`), or absence from a later full vintage (Eurostat, OECD), closes
  the open interval;
- attributes that can change by vintage, such as the OECD base period, are part of the
  content, so a rebasing shows up as a new interval rather than a silent revision.

Vintage tables split across datasets share a **family** (`ESTAT:ei_lm_m_vtgfix` 2001–2020 and
`ESTAT:ei_lm_m_vtg` 2021 onward form one series). Without this the last vintage of the old
table would stay "current" forever.

## Stable identities

- `series_id = md5(family | series_key)` and `snapshot_id = md5(path)`, so identities survive
  rebuilds.
- Observations are referenced by their natural key `(series_id, period, known_from)`.
- `model.assessment_input` references observations with `ON DELETE RESTRICT`: evidence an
  assessment used cannot disappear.

## Regions

Source systems name the euro area differently: ECB `U2`, ECB RTD `S0`, Eurostat `EA`,
`EA20`, `EA21`, OECD `EA19` or `EA20` by edition. `ref.region_alias` maps them to canonical
regions. `EA` is the official changing-composition aggregate; `EA19`, `EA20` and `EA21` are
fixed compositions. Splicing series across codes is an explicit, versioned choice in
`model.indicator_component` with a knowledge window (`serves`), never an implicit join.

## Model layer and the concept's core requirements

| Requirement (concept section 21) | Where it is enforced |
|---|---|
| 1 Traceable to evidence and source data | `assessment_input` → `observation` → `snapshot` → file and URL |
| 2 Raw separate from derived | `raw` and `obs` hold no interpretation; `model` holds all of it |
| 3 Correlation, mechanism, causality not conflated | `model.evidence_status` enum on edges |
| 4 Supporting and contradicting evidence | `evidence_claim.stance`, `assessment_input.role` |
| 5 Vintages and knowledge time preserved | bitemporal `obs.observation` |
| 6 Uncertainty explicit | three separate columns on `assessment` |
| 7 Definitions versioned | `model_version` referenced by nodes, indicators, edges, assessments |
| 8 Regional applicability explicit | `region_code` on indicators, edges, claims, assessments |
| 9 AI subordinate to evidence | `llm_claims_need_review` constraint |
| 10 Backtests use only data known then | `obs.as_of` defaults |
| 11 Model can change its view | assessments are versioned rows, never updated in place |

## Example

```sql
-- Euro area unemployment as it was known at the end of 2019
SELECT a.period_label, a.value, a.known_from
FROM obs.as_of('2019-12-31') a
JOIN obs.series s USING (series_id)
WHERE s.family = 'ESTAT:ei_lm_m_vintages'
ORDER BY a.period DESC LIMIT 3;
```

## Known gaps

- Eurostat industrial production vintages 2001–2020 are not yet pulled (size cap, needs
  chunking).
- Energy prices, unit labour costs and government debt only have `ingestion` knowledge.
  Backtests need the OECD revisions database (ULC) or ECB RTD (deficit ratios) instead.
- ENTSO-E is waiting for an API token.
