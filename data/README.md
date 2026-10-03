# Data archive and attribution

Everything the project pulls from upstream is committed here, byte for byte, so the database
and every assessment can be rebuilt and audited without contacting the providers again.

| Path | Contents |
|---|---|
| `raw/<card_id>/<UTC timestamp>__<label>.<ext>` | Statistical data as downloaded (`.gz` when above 5 MB, lossless) |
| `raw/<card_id>/...meta.json` | Exact URL, retrieval time (UTC), HTTP status, size, SHA-256 |
| `raw/documents/<doc_id>/...` | Source documents cited as evidence, with the same metadata |

Each dataset is described by a source card in `../sources/` (provider, licence, terms URL,
revision policy, knowledge-time rule, known pitfalls). Cited documents are listed in
`../model/documents.yaml`.

## Attribution

Data and documents remain the property of their providers and are redistributed here for
research and audit under their reuse terms. Check the terms URL on each source card before
any other use.

- **European Central Bank** (ECB Data Portal, ECB Real-Time Database, ECB publications).
  Source: European Central Bank. Reuse is permitted provided the source is acknowledged.
- **Eurostat** (European Commission). Source: Eurostat. Reuse under the Commission's reuse
  policy (CC BY 4.0).
- **OECD** (Short-term economic statistics revisions database). Source: OECD. Reuse under the
  OECD Terms and Conditions.

Derived values in the database are computations by this project, not official statistics.
