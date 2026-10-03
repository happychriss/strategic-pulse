# Network allowlist for the cloud environment

Package managers (PyPI, apt, GitHub) already work. These are the data hosts needed, grouped by phase.
In the environment settings choose Network access, Custom, add the domains, and keep the default
package-manager list enabled.

## Phase 0 and 1 (needed now)

```
ec.europa.eu
data-api.ecb.europa.eu
data.ecb.europa.eu
www.ecb.europa.eu
sdmx.oecd.org
data-explorer.oecd.org
www.oecd.org
web-api.tp.entsoe.eu
transparency.entsoe.eu
```

## Phase 2

```
api.imf.org
data.imf.org
api.worldbank.org
```

## Phase 3

```
www.v-dem.net
v-dem.net
www.matteoiacoviello.com
www.policyuncertainty.com
fred.stlouisfed.org
eur-lex.europa.eu
parlgov.org
www.gdeltproject.org
data.gdeltproject.org
api.globaltradealert.org
api.acleddata.com
cds.climate.copernicus.eu
```

## Secrets

ENTSO-E needs a free token. Add it as an environment secret named `ENTSOE_API_TOKEN`. Never commit it.
