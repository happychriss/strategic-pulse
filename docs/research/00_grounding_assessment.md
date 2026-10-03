# Strategic Regime Monitor: grounding assessment before build

Date: 2026-10-03
Status: research note, no code. Input: `strategic_regime_monitor_concept.md` (concept baseline).

## 1. Verdict

The concept is methodologically sound and unusually disciplined. Its risk is not
design quality. Its risk is that it is a *framework* with no bounded first
deliverable, and frameworks of this kind become endless work. Four things make
it open-ended as written:

1. Nine axes, a dozen state variables, six regimes, several regions and a
   rolling backtest multiply into hundreds of indicator onboarding tasks.
2. The "active dynamics" and "regime engine" steps have no defined algorithm.
   This is the hidden research project inside the system.
3. Bitemporal (vintage) data, which the backtest requires, exists for a small
   set of macro series only. Most structural indicators are annual and revised
   wholesale on each release.
4. Apache AGE and pgvector add stack and operations risk before there is any
   graph or any documents to embed.

Recommendation: keep the concept as the target architecture, but commit to a
single thin vertical slice with a written exit criterion, and treat source
onboarding (data discovery) as the first workstream with its own deliverable.

## 2. What is strong and should not be diluted

- Separation of observation, relationship and assessment layers.
- Bitemporal thinking (valid time vs knowledge time) from day one.
- Counter-evidence and "what would change our view" as first-class objects.
- Qualitative regime movement before probabilities.
- Model versioning separating "world changed" from "model changed".
- Compact stack, Postgres as system of record.

## 3. Data discovery: what actually exists

Reachability column: tested from this cloud session on 2026-10-03. Every host
below returned "CONNECT tunnel failed, 403" from the egress proxy. The
environment's network policy must be widened before any ingestion code can be
run here (see section 8).

| Source | Access | Vintages (knowledge time) | Notes |
|---|---|---|---|
| Eurostat REST / SDMX | Free, keyless | Only for 3 indicators: GDP, unemployment, industrial production (monthly vintage tables) | Main DB holds latest values only. Revision policy published. |
| ECB Data Portal API | Free, keyless | RTD dataset: 200+ euro area series, vintages 2001 onwards, semi-annual update; `includeHistory=true` for history since 2015 | Best European real-time source. SDMX 2.1 REST. |
| OECD Data Explorer API (SDMX 3.0) | Free, rate limited | MEI "Original Release Data and Revisions" DB, monthly vintages from 1999 | API changed 2024; third-party mirrors (DBnomics) broke. |
| IMF Data Portal (SDMX 3.0) | Free | WEO editions are natural vintages (April/October) | Legacy API retired mid-2025. |
| World Bank API (WDI, WGI) | Free | Annual releases; no vintage API | WGI revised back-history each release. |
| DBnomics | Free aggregator, 90+ providers | Stores every revision internally, but API cannot serve vintages yet | Useful for discovery, not for knowledge time. |
| V-Dem | Free download | Dataset archive v1 to v16 = usable release vintages | Whole history recoded per version. Knowledge time = release version. |
| EPU Europe, GPR country indices | Free CSV (also FRED) | None, but news-based so revisions are small | Monthly. |
| ACLED | Registration, tiered; civil society/academic broad, corporate 1 year | None | Terms limit redistribution. |
| GDELT | Free, BigQuery and raw files | Append-only by nature | Noisy; event coding needs filtering. |
| Global Trade Alert | API key, self-serve demo | Events dated by announcement | Trade restriction events. |
| EU Sanctions Map / OpenSanctions | Free API | Legal acts dated | Sanctions events. |
| ParlGov | Free | Release-based | Elections, cabinets for EU/OECD. |
| ENTSO-E, Energy-Charts, SMARD | Free with token / free | Operational data, not revised much | Energy prices and load. |
| IEA energy prices | Paid licence for most | n/a | Avoid as a dependency; use Eurostat energy, ENTSO-E, gas TTF proxies. |
| Copernicus CDS (ERA5) | Free, token, per-dataset terms | Reanalysis versions | Heavy; aggregate to country level offline. |

Implication for the backtest: a rolling 2010 to 2020 backtest with true
knowledge time is feasible for the euro area macro layer (ECB RTD, OECD MEI
revisions, Eurostat 3 series). It is not feasible for governance, cohesion or
climate axes beyond "release version" granularity. The concept should say so.

## 4. Comparable systems and what to borrow

- JRC Resilience Dashboards (EU): four dimensions, indicator sets audited by
  JRC-COIN, aligned to the European Semester. Closest existing analogue to the
  "structural axes". Borrow their indicator lists rather than inventing ours.
- ESRB Risk Dashboard: quarterly indicator set, explicitly "not an early
  warning system". Same humility the concept wants. Excel downloads.
- OECD/JRC Handbook on Composite Indicators (2008) and COINr (R): the reference
  for normalisation, weighting, aggregation and sensitivity analysis. Python
  has no equivalent of COINr's maturity; CIF covers leading indicators only.
- ECB RTD / EABCN: the model for storing vintages as snapshots per release.
- Our World in Data ETL: snapshot raw files, pure-function steps, DAG of
  dependencies, channels (meadow/garden). Best open design for provenance in
  Python. Borrow the snapshot-first pattern.
- Intelligence analysis techniques: Analysis of Competing Hypotheses and
  Indicators and Warnings. These are the closest formal method to "regime
  assessment with supporting and contradicting evidence and transition
  conditions". No good open-source tooling exists; a Postgres table design is
  enough.
- Causal knowledge graphs from economics papers (LLM extraction over NBER/CEPR
  corpora, FinCausal): proves the evidence-claim extraction is doable, also
  shows the output is a hypothesis layer, which matches the concept.
- Markov-switching and regime-switching factor models (statsmodels, IMF WP
  2024): the statistical side of "regime". Useful later as one input, not as
  the regime engine.

Nobody has combined these into a traceable, bitemporal regime monitor in the
open. That is the genuine gap. It is also why there is no template to copy.

## 5. Technology checks

| Component | Finding | Recommendation |
|---|---|---|
| PostgreSQL 18 | Temporal PK `WITHOUT OVERLAPS` and temporal FK `PERIOD` are native | Use PG18; implement valid/knowledge time with ranges and native constraints, no extension. |
| Apache AGE | Active, 1.7/1.8 in 2026, supports PG17/18; still relational underneath, performance caveats, release candidates on some distros | Defer. Relationship graph will have tens to low hundreds of edges for years; recursive CTEs suffice. Keep node/edge tables AGE-loadable. |
| pgvector | Mature | Defer until a document ingestion workflow exists. |
| sdmx1 (Python) | Actively maintained in 2026, SDMX 2.1 and 3.0, sources for Eurostat, ECB, OECD, IMF, World Bank | Use as the single SDMX client. |
| DBnomics | Convenient but no vintages, OECD feed stale since late 2024 | Discovery aid only. |

## 6. Proposed trajectory with exit criteria

### Phase 0: Source onboarding and data discovery (deliverable: a registry, not code)

- One "source card" per dataset: provider, endpoint, licence, frequency,
  release calendar, revision policy, vintage availability, geography, unit,
  Python access path, known pitfalls. Stored as structured YAML or a Postgres
  table so it becomes the `source`/`dataset` object later.
- Start with the sources needed by Phase 1 only. The card format is the
  reusable onboarding mechanism for every future source.
- Exit: every Phase 1 indicator has a card and one successful manual pull.

### Phase 1: Thin vertical slice

- Region: euro area.
- Regime pair: higher-for-longer vs recession/disinflation.
- Axes: Resources/Energy and Fiscal Capacity only.
- State variables: HICP headline and core, policy rate, 10-year yields, unit
  labour costs, unemployment.
- Indicators: about ten, all from ECB RTD, Eurostat, OECD MEI, ENTSO-E or
  Eurostat energy.
- Relationships: five to eight, entered by hand with evidence citations
  (ECB Economic Bulletin boxes are good sources).
- Storage: plain Postgres with valid/knowledge time ranges. Raw payload
  snapshots stored as files, OWID style.
- Output: one text page per assessment date that walks the trace
  Regime -> Active dynamics -> Relationships -> Indicators -> Observations -> Source,
  plus counter-evidence and transition conditions.
- Exit: run the pipeline "as of" four dates (end-2019, end-2021, end-2022,
  end-2024) using only vintage data available then. The output must show the
  shift into higher-for-longer and the later easing, with the trace intact.
  If it cannot, the methodology is wrong and should be fixed before any
  widening.

### Phase 2: Methodology hardening

- Normalisation and aggregation following the JRC/OECD handbook, documented
  and versioned. Model-version table live.
- First statistical support (trend, momentum, simple regime-switching on the
  state variables) as a *comparison*, not as the engine.
- Exit: a change in weights or definitions produces a new model version and
  historical assessments remain reproducible.

### Phase 3: Widening

- Add Governance and Societal Cohesion with V-Dem release vintages and EPU/GPR.
- Add events (sanctions, trade restrictions, elections) from the free sources.
- Add document ingestion with LLM claim extraction, pgvector only now.
- Add a second region (Germany) to prove geography independence.

### Explicitly out of scope until Phase 3 exits

Dashboards beyond a text page, news filter, Cypher/AGE, probabilities,
non-European regions, automated AI relationship discovery.

## 7. Changes I would make to the concept document

1. Add a "first deliverable and exit criterion" section (Phase 1 above).
2. State the vintage reality: full knowledge-time backtesting is limited to the
   macro layer; structural axes get release-version granularity.
3. Replace "Apache AGE" in the baseline with "graph-shaped relational tables,
   AGE optional later". Same for pgvector.
4. Add "Source onboarding card" as a core information object. It is the
   concrete form of Source/Dataset and the mechanism for onboarding new data.
5. Add a short "what this is not" list: not an early warning system, not a
   news aggregator, not a forecasting model. The ESRB wording is a good model.
6. Define the regime engine's first version honestly: a rule table over
   normalised state variables and axis directions, written by hand, with
   evidence columns. Statistics come later as a challenger.

## 8. Environment blocker

This cloud session's network policy denies every data host tested, including
`ec.europa.eu`, `data-api.ecb.europa.eu`, `sdmx.oecd.org`, `api.worldbank.org`,
`api.db.nomics.world`, `api.imf.org`, `cds.climate.copernicus.eu`,
`web-api.tp.entsoe.eu`. Widen Network access in the environment settings
(cloud environment menu in the session title bar, then Edit) to a broader level
or add these domains under Allowed domains. Until then, ingestion work has to
run locally.

## 9. Open questions for the owner

1. Who reads the output, and how often: you alone, monthly; or others?
2. Is development local (Docker Postgres) or in this cloud environment?
3. Is a paid source acceptable at all (IEA, ACLED corporate tier)? Proposal: no.
4. Is a Python-only analytical layer acceptable even though COINr (R) is the
   reference composite-indicator toolkit? Proposal: yes, port what is needed.

## Sources consulted

- Eurostat revision policy and euro indicators vintages: https://ec.europa.eu/eurostat/web/euro-indicators/information-data , https://ec.europa.eu/eurostat/data/data-revision-policy
- ECB RTD dataset and API history: https://data.ecb.europa.eu/data/datasets/RTD/data-information , https://eabcn.org/data/eabcn-real-time-database
- OECD API and MEI revisions database: https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html , https://www.oecd.org/en/publications/undertaking-revisions-and-real-time-data-analysis-using-the-oecd-main-economic-indicators-original-release-data-and-revisions-database_146528313656.html
- IMF Data Portal transition: https://data.imf.org/-/media/iData/External-Storage/Documents/2C2B2F3E671A4B11ABE756E2441FD6F0/en/WEO-Database-Transition-Guide.pdf
- DBnomics vintages status: https://dbnomics.discourse.group/t/data-vintages/299 , https://dbnomics.discourse.group/t/oecd-dataset-access-updates-rip/929
- V-Dem archive: https://www.v-dem.net/en/data/archive/previous-data/v-dem-dataset
- ACLED access model: https://acleddata.com/myacled-faqs ; GDELT: https://www.gdeltproject.org/data.html
- GPR: https://www.matteoiacoviello.com/gpr_country.htm ; EPU Europe: https://fred.stlouisfed.org/series/EUEPUINDXM/
- Global Trade Alert API: https://globaltradealert.org/api-access/quickstart ; ParlGov: https://parlgov.org/data-info/ ; OpenSanctions EU map: https://opensanctions.org/datasets/eu_sanctions_map
- IEA licensing: https://www.iea.org/data-and-statistics/data-product/energy-prices ; ENTSO-E API: https://www.opennetzero.org/entso-e/entso-e-transparency-platform-api
- CDS: https://forum.ecmwf.int/t/goodbye-legacy-climate-data-store-hello-new-climate-data-store-cds/6380
- JRC Resilience Dashboards: https://joint-research-centre.ec.europa.eu/scientific-activities/resilience/resilience-dashboards_en ; ESRB dashboard: https://www.esrb.europa.eu/pub/pdf/dashboard/esrb.risk_dashboard_external_260331~1c80e0b575.en.pdf
- JRC/OECD handbook and COINr: https://knowledge4policy.ec.europa.eu/sites/default/files/jrc47008_handbook_final.pdf , https://stat.ethz.ch/CRAN/web/packages/COINr/refman/COINr.html ; CIF: https://github.com/LenkaV/CIF
- OWID ETL design: https://owid-docs.readthedocs.io/projects/etl/architecture/
- Apache AGE releases: https://age.apache.org/release-notes , https://www.enterprisedb.com/docs/pg_extensions/apache_age/rel_notes/apache_age_1.8.0_rel_notes/
- PostgreSQL 18 temporal constraints: https://neon.com/postgresql/18/temporal-constraints
- sdmx1: https://sdmx1.readthedocs.io/en/latest/whatsnew.html
- Causal KG from economics papers: https://cepr.org/voxeu/columns/leveraging-large-language-models-large-scale-information-retrieval-economics ; regime-switching nowcasting: https://www.imf.org/en/publications/wp/issues/2024/09/06/regime-switching-factor-models-and-nowcasting-with-big-data-554116
- Structured analytic techniques: https://en.wikipedia.org/wiki/Indicator_analysis
