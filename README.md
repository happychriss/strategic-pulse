# Strategic Regime Monitor

An evidence-driven, bitemporal system for observing structural change and assessing regime
transitions. Europe first. Every assessment must trace back to observations and sources.

| Path | Contents |
|---|---|
| `docs/research/00_grounding_assessment.md` | Assessment of the concept, data landscape and phased plan |
| `docs/data_model.md` | Database design: time axes, knowledge rules, provenance |
| `docs/model_review.md` | Model content, review workflow, first findings |
| `model/` | Versioned model definitions, cited documents, evidence claims |
| `sources/` | Source cards, one per dataset (`python -m srm.source_cards` validates) |
| `data/raw/` | Raw upstream snapshots and cited documents with metadata (see `data/README.md`) |
| `db/migrations/` | PostgreSQL 16 schema |
| `scripts/pull_phase1.py` | Pulls Phase 1 snapshots (skips existing ones) |
| `scripts/pull_documents.py` | Archives documents cited by claims |
| `src/srm/` | Snapshot archive, parsers, knowledge rules, build, indicators, regime conditions |

```bash
python scripts/pull_phase1.py   # fetch missing snapshots
python -m srm.build             # migrate and rebuild the database from snapshots
pytest                          # unit and integration tests
```

In Claude Code cloud sessions the session-start hook installs dependencies, starts
PostgreSQL and runs the build.
