# Strategic Regime Monitor

An evidence-driven, bitemporal system for observing structural change and assessing regime
transitions. Europe first. Every assessment must trace back to observations and sources.

| Path | Contents |
|---|---|
| `docs/research/00_grounding_assessment.md` | Assessment of the concept, data landscape and phased plan |
| `docs/data_model.md` | Database design: time axes, knowledge rules, provenance |
| `docs/model_review.md` | Model content, review workflow, first findings |
| `docs/operations.md` | Monthly routine: what it does, guardrails, routine prompt |
| `model/` | Versioned model definitions (`versions/`), cited documents, evidence claims |
| `reports/assessments/` | Generated assessment pages per model version (Markdown per cutoff, one HTML page) |
| `reports/runs/` | Run logs: what each monthly run pulled and what changed |
| `sources/` | Source cards, one per dataset (`python -m srm.source_cards` validates) |
| `data/raw/` | Raw upstream snapshots and cited documents with metadata (see `data/README.md`) |
| `db/migrations/` | PostgreSQL 16 schema |
| `src/srm/pull.py` | Pull manifest; archives a snapshot only when content changed |
| `scripts/pull_documents.py` | Archives documents cited by claims |
| `src/srm/` | Snapshot archive, parsers, knowledge rules, build, indicators, regime conditions, assessments, pages |

```bash
python -m srm.run_monthly       # the monthly run: pull, build, test, assess, pages, run log
python -m srm.pull              # refresh all snapshots (only changed content is archived)
python -m srm.build             # migrate and rebuild the database from snapshots
python -m srm.assess            # assess the Phase 1 cutoffs and now, write the pages
pytest                          # unit and integration tests
```

In Claude Code cloud sessions the session-start hook installs dependencies, starts
PostgreSQL and runs the build.
