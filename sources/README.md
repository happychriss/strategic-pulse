# Source cards

One YAML file per dataset. A card is how any new data enters the project: no card, no ingestion.
The filename equals the card `id`. Validate with:

```bash
python -m srm.source_cards
```

## Required fields

| Field | Meaning |
|---|---|
| `id`, `provider`, `name` | Identity. `id` equals the filename. |
| `role` | `structural_indicator`, `state_variable`, `event` or `context`. |
| `phase` | 1, 2 or 3 per the project trajectory. Only Phase 1 cards are in scope now. |
| `endpoint` | Protocol, base URL, dataset ID, an example key. |
| `access` | Auth type (`none`, `free_token`, `registration`, `paid`), licence, terms URL. |
| `coverage` | Geography, frequency, start. |
| `temporal` | Revision policy, `vintage_support` (`none`, `release_snapshots`, `full_history`), and what defines knowledge time for this source. |
| `python_access` | How we pull it. |
| `pitfalls` | Known traps, written as a list. |
| `verification` | `unverified` until a real pull succeeded; then `verified` with date. |
| `docs_urls` | Authoritative documentation. |

## Rules

- A card starts `unverified`. Promote it only after a successful pull that confirms dataset code, key structure and licence.
- `knowledge_time_basis` must say what the database stores as knowledge time. If the source has no vintages, it is the ingestion timestamp and every pull is archived untouched.
- Secrets (tokens) never go in a card. Name the environment variable instead.

## Phase 0 exit

Every Phase 1 card is `verified` and one raw snapshot per card is archived under `data/raw/`.

## Backlog (no card yet, Phase 3)

ACLED, GDELT, Global Trade Alert, EU Sanctions Map, ParlGov, Copernicus CDS, World Bank WGI.
