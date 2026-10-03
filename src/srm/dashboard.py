"""Newsletter dashboard: the current situation in Europe on one page, in German.

Everything shown comes from the detector result (`reports/detector/<version>.json`) and the
database: monthly signals with ten years of history, the yearly structural trends, and for every
number the source card, dataset and retrieval date it rests on. The page states what is moving
now; it makes no forecast.

    python -m srm.dashboard
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path

import psycopg

from srm.db import connect
from srm.detect import version_id
from srm.indicators import indicator_series
from srm.model_content import current_label
from srm.structural import config as structural_config
from srm.structural import eu_series, known_year, load_panel, slope

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "reports" / "dashboard"
HISTORY_YEARS = 5
STRUCTURAL_YEARS = 20

LAYERS_DE = {
    "prices_policy": "Preise und Geldpolitik",
    "real_economy": "Realwirtschaft",
    "resources_energy": "Rohstoffe und Energie",
    "international_integration": "Internationale Verflechtung",
    "societal_cohesion": "Gesellschaftlicher Zusammenhalt",
    "demography_migration": "Demografie und Migration",
}

# indicator -> (German name, unit of the level, unit of a change)
SIGNALS_DE = {
    "ea_hicp_headline_yoy": ("Inflation (HVPI)", "%", "Pp."),
    "ea_hicp_core_yoy": ("Kerninflation ohne Energie und Lebensmittel", "%", "Pp."),
    "ea_policy_rate": ("EZB-Einlagezins", "%", "Pp."),
    "ea_10y_yield": ("Rendite 10-jähriger Staatsanleihen (AAA)", "%", "Pp."),
    "ea_household_price_expectations": ("Preiserwartungen der Haushalte", "Saldo", "Punkte"),
    "ea_unemployment_rate": ("Arbeitslosenquote", "%", "Pp."),
    "ea_gdp_qoq": ("Wachstum zum Vorquartal", "%", "Pp."),
    "ea_economic_sentiment": ("Wirtschaftsstimmung (ESI)", "Index", "Punkte"),
    "ea_industry_confidence": ("Vertrauen in der Industrie", "Saldo", "Punkte"),
    "ea_hicp_energy_yoy": ("Energiepreise zum Vorjahr", "%", "Pp."),
    "eu_gas_imports_russia_share": ("Russlands Anteil an den EU-Gasimporten", "%", "Pp."),
    "ea_export_volume_yoy": ("Exportvolumen zum Vorjahr", "%", "Pp."),
    "ea_import_volume_yoy": ("Importvolumen zum Vorjahr", "%", "Pp."),
    "ea_consumer_confidence": ("Verbrauchervertrauen", "Saldo", "Punkte"),
    "ea_unemployment_fears": ("Sorge vor Arbeitslosigkeit", "Saldo", "Punkte"),
    "ea_youth_unemployment": ("Jugendarbeitslosigkeit (unter 25)", "%", "Pp."),
    "eu_asylum_applicants": ("Asylerstanträge je 100.000 Einwohner", "", ""),
}

STRUCTURAL_DE = {
    "rule_of_law": ("Rechtsstaatlichkeit", "Weltbank-Index", "Regierungsführung"),
    "voice_accountability": ("Mitsprache und Rechenschaft", "Weltbank-Index", "Regierungsführung"),
    "corruption_perceptions": (
        "Korruptionswahrnehmung (höher = sauberer)",
        "Punkte",
        "Regierungsführung",
    ),
    "income_inequality": ("Einkommensungleichheit", "S80/S20", "Zusammenhalt"),
    "gov_expenditure": ("Staatsausgaben", "% des BIP", "Wirtschaftsordnung"),
    "old_age_dependency": ("Altenquotient", "65+ je 100 im Alter 15–64", "Demografie"),
    "fertility": ("Geburtenrate", "Kinder je Frau", "Demografie"),
    "rd_intensity": ("Forschungsausgaben", "% des BIP", "Technologie"),
    "climate_losses": ("Schäden durch Klimaextreme", "€ je Einwohner", "Klima"),
    "energy_import_dependency": ("Energieimportabhängigkeit", "%", "Energie"),
    "gov_debt": ("Staatsschulden", "% des BIP", "Staatsfinanzen"),
}

EVENTS_DE = {
    "new alarm": "neu erkannt",
    "alarm already running": "Alarm lief bereits",
    "missed": "verpasst",
}

COUNTRIES_DE = {
    "AT": "Österreich", "BE": "Belgien", "BG": "Bulgarien", "CY": "Zypern", "CZ": "Tschechien",
    "DE": "Deutschland", "DK": "Dänemark", "EE": "Estland", "EL": "Griechenland", "ES": "Spanien",
    "FI": "Finnland", "FR": "Frankreich", "HR": "Kroatien", "HU": "Ungarn", "IE": "Irland",
    "IT": "Italien", "LT": "Litauen", "LU": "Luxemburg", "LV": "Lettland", "MT": "Malta",
    "NL": "Niederlande", "PL": "Polen", "PT": "Portugal", "RO": "Rumänien", "SE": "Schweden",
    "SI": "Slowenien", "SK": "Slowakei",
}  # fmt: skip

MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]  # fmt: skip


# ------------------------------------------------------------------ formatting


def num(v: float | None, digits: int = 1, sign: bool = False) -> str:
    """German number format: decimal comma, thin space as thousands separator, real minus."""
    if v is None:
        return "–"
    s = f"{v:+,.{digits}f}" if sign else f"{v:,.{digits}f}"
    return s.replace(",", " ").replace(".", ",").replace("-", "−")


def digits_for(values: list[float]) -> int:
    top = max((abs(v) for v in values), default=0)
    return 0 if top >= 100 else 1 if top >= 1 else 2


def period_de(label: str) -> str:
    """'2026-09' -> '09/2026', '2026-Q2' -> 'Q2/2026', '2024' -> '2024'."""
    if "-Q" in label:
        y, q = label.split("-")
        return f"{q}/{y}"
    if len(label) == 7:
        return f"{label[5:]}/{label[:4]}"
    return label


def month_de(month: str) -> str:
    return f"{MONTHS_DE[int(month[5:7]) - 1]} {month[:4]}"


def day_de(d: date) -> str:
    return f"{d.day}. {MONTHS_DE[d.month - 1]} {d.year}"


def _e(text) -> str:
    return escape(str(text), quote=True)


# ------------------------------------------------------------------ data


def provenance_for_families(conn: psycopg.Connection, families: list[str]) -> list[dict]:
    rows = conn.execute(
        """SELECT sc.card_id, sc.provider, sc.name, string_agg(DISTINCT d.dataset_id, ', ') FILTER (WHERE EXISTS (
                      SELECT 1 FROM raw.snapshot sn
                      WHERE sn.dataset_id = d.dataset_id AND sn.load_status = 'loaded')),
                  sc.card->'access'->>'licence', sc.card->'access'->>'terms_url',
                  sc.card->'docs_urls'->>0, sc.card->'endpoint'->>'base_url',
                  (SELECT max(retrieved_at) FROM raw.snapshot sn
                    WHERE sn.card_id = sc.card_id AND sn.load_status = 'loaded')
           FROM ref.dataset d JOIN ref.source_card sc USING (card_id)
           WHERE d.family = ANY(%s)
           GROUP BY sc.card_id ORDER BY sc.card_id""",
        (families,),
    ).fetchall()
    return [
        {
            "card": r[0],
            "provider": r[1],
            "name": r[2],
            "datasets": r[3],
            "licence": r[4] or "",
            "url": r[6] or r[5] or r[7] or "",
            "retrieved": r[8].date().isoformat() if r[8] else None,
        }
        for r in rows
    ]


def indicator_families(conn: psycopg.Connection, code: str, mv: int, at: datetime) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT s.family FROM model.indicator_component c
           JOIN model.indicator i USING (indicator_id) JOIN obs.series s USING (series_id)
           WHERE i.code = %s AND i.model_version_id = %s AND c.serves @> %s::timestamptz""",
        (code, mv, at),
    ).fetchall()
    return [r[0] for r in rows]


def signal_history(conn, code: str, mv: int, at: datetime) -> tuple[list[list], dict | None]:
    """Last HISTORY_YEARS of values, and where the latest value stands in the full history."""
    pts = indicator_series(conn, code, at, mv)
    start = date(at.year - HISTORY_YEARS, at.month, 1)
    return [[p[1], round(p[2], 4)] for p in pts if p[0] >= start], level_context(pts)


def level_context(pts: list) -> dict | None:
    """Share of all earlier periods with a lower value than the latest one (0..1)."""
    if len(pts) < 24:
        return None
    *past, last = [p[2] for p in pts]
    return {
        "rank": round(sum(v < last for v in past) / len(past), 3),
        "since": pts[0][1][:4],
        "periods": len(past),
    }


def structural_series(conn, ind: dict, aggregate: str, at: datetime) -> list[list]:
    panel = load_panel(conn, ind["family"], ind["match"])
    _, agg, _ = eu_series(panel, ind, aggregate, known_year(at, ind.get("lag_months", 9)))
    if not agg:
        return []
    last = max(agg)
    return [[y, round(agg[y], 4)] for y in sorted(agg) if y > last - STRUCTURAL_YEARS]


def build_payload(conn: psycopg.Connection, label: str | None = None) -> dict:
    label = label or current_label()
    det_path = ROOT / "reports" / "detector" / f"{label}.json"
    det = json.loads(det_path.read_text(encoding="utf-8"))
    mv = version_id(conn, label)
    at = datetime.now(UTC)
    sources: dict[str, dict] = {}

    def remember(provs: list[dict]) -> list[str]:
        for p in provs:
            sources.setdefault(p["card"], p)
        return [p["card"] for p in provs]

    signals = []
    for s in det["now"]["signals"]:
        provs = provenance_for_families(conn, indicator_families(conn, s["indicator"], mv, at))
        signals.append(
            {
                **s,
                **dict(zip(("history", "level"), signal_history(conn, s["indicator"], mv, at))),
                "sources": remember(provs),
            }
        )
    cfg = structural_config(label)
    by_key = {i["key"]: i for i in cfg["indicators"]}
    structural = []
    for r in det["structural_now"]:
        ind = by_key[r["key"]]
        provs = provenance_for_families(conn, [ind["family"]])
        structural.append(
            {
                **r,
                "series": structural_series(conn, ind, cfg["aggregate"], at),
                "trend_years": cfg["trend_years"],
                "sources": remember(provs),
            }
        )
    flagged_years = {
        r["key"]: [int(y) for y, rows in det["structural_history"].items() for x in rows
                   if x["key"] == r["key"] and x["unusual"]]
        for r in det["structural_now"]
    }  # fmt: skip
    return {
        "model_version": label,
        "generated_utc": det["generated_utc"],
        "now": {k: v for k, v in det["now"].items() if k != "signals"},
        "layers": det["layers"],
        "signals": signals,
        "timeline": det["timeline"],
        "events": det["events"],
        "test": det["test_summary"][label],
        "structural": structural,
        "structural_flagged_years": flagged_years,
        "sources": sorted(sources.values(), key=lambda p: (p["provider"], p["card"])),
    }


# ------------------------------------------------------------------ wording


def trend_words(now: float | None, before: float | None, level: float | None, turn: bool) -> str:
    if now is None or before is None:
        return "Trend nicht bestimmbar (Lücken)"
    flat = 0.003 * abs(level or 1)
    word = {1: "steigt", -1: "fällt"}

    def sgn(v: float) -> int:
        return 0 if abs(v) <= flat else (1 if v > 0 else -1)

    a, b = sgn(now), sgn(before)
    if a == 0:
        return "seitwärts" if b == 0 else f"kommt zum Stillstand (zuvor: {word[b]})"
    if turn or (b != 0 and a != b):
        return f"Trend dreht: {word[a]} jetzt"
    if b == 0:
        return f"{word[a]} wieder (zuvor seitwärts)"
    if abs(now) > 1.25 * abs(before):
        return f"{word[a]} schneller"
    if abs(now) < 0.8 * abs(before):
        return f"{word[a]} langsamer"
    return f"{word[a]} gleichmäßig"


def signal_state(s: dict) -> tuple[str, str]:
    """(css class, German label) for one signal."""
    if s["unusual"]:
        return "move", "Tempo ungewöhnlich"
    if s["turn"]:
        return "turn", "Richtungswechsel"
    return "calm", "Tempo üblich"


def level_extreme(s: dict) -> str | None:
    """'hoch' or 'niedrig' when the level sits in the outer tenth of its own history."""
    lv = s.get("level")
    if not lv:
        return None
    return "hoch" if lv["rank"] >= 0.9 else "niedrig" if lv["rank"] <= 0.1 else None


def level_words(s: dict) -> str:
    lv = s.get("level")
    if not lv:
        return "Niveau: zu kurze Geschichte für eine Einordnung"
    unit = "Quartale" if "-Q" in s["latest_period"] else "Monate"
    if lv["rank"] >= 0.5:
        return f"Niveau: höher als in {lv['rank']:.0%} aller {unit} seit {lv['since']}".replace(
            "%", " %"
        )
    return f"Niveau: niedriger als in {1 - lv['rank']:.0%} aller {unit} seit {lv['since']}".replace(
        "%", " %"
    )


def headline(p: dict) -> tuple[str, str]:
    now = p["now"]
    names = [LAYERS_DE.get(k, k) for k in now["active_layers"]]
    if now["level"] == 0:
        return "calm", "Ruhige Lage. Keine Ebene bewegt sich ungewöhnlich."
    if now["level"] == 1:
        return "move", f"Eine Ebene in Bewegung: {names[0]}."
    lead = "Neu: mehrere Ebenen in Bewegung" if now["onset"] else "Mehrere Ebenen in Bewegung"
    return "alarm", f"{lead}: {', '.join(names)}."


def explain_signal(s: dict) -> str:
    name, _, cu = SIGNALS_DE.get(s["indicator"], (s["indicator"], "", ""))
    if s["unusual"]:
        way = "Anstieg" if (s["change"] or 0) > 0 else "Rückgang"
        return (
            f"{name}: ungewöhnlich schneller {way}, {num(s['change'], 1, True)} {cu} in drei "
            f"Monaten (üblich sind bis zu ±{num(s['threshold'])})."
        )
    way = "nach unten" if (s["change_6m"] or 0) < 0 else "nach oben"
    return (
        f"{name}: Richtungswechsel {way}, {num(s['change_6m'], 1, True)} {cu} in sechs Monaten "
        f"nach einer längeren Bewegung in die Gegenrichtung."
    )


# ------------------------------------------------------------------ drawing


def sparkline(points: list[list], window: int, state: str) -> str:
    """Monthly or quarterly history as a line with area fill, last `window` points marked."""
    if len(points) < 2:
        return '<p class="nodata">Zu wenig Daten</p>'
    w, h, pad = 560, 76, 5
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    span = hi - lo
    lo, hi = lo - span * 0.08, hi + span * 0.08

    def x(i):
        return pad + i * (w - 2 * pad) / (len(points) - 1)

    def y(v):
        return pad + (hi - v) * (h - 2 * pad) / (hi - lo)

    line = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(points))
    base = y(max(lo, min(hi, 0))) if lo < 0 < hi else h - pad
    area = f"{x(0):.1f},{base:.1f} {line} {x(len(points) - 1):.1f},{base:.1f}"
    k = max(0, len(points) - 1 - window)
    parts = [
        (
            f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Verlauf {points[0][0]} bis {points[-1][0]}" '
            f"data-points='{_e(json.dumps(points))}'>"
        ),
        f'<rect x="{x(k):.1f}" y="0" width="{w - pad - x(k):.1f}" height="{h}" class="win {state}"/>',
    ]
    if lo < 0 < hi:
        parts.append(
            f'<line x1="{pad}" x2="{w - pad}" y1="{base:.1f}" y2="{base:.1f}" class="zero"/>'
        )
    parts += [
        f'<polygon points="{area}" class="area"/>',
        f'<polyline points="{line}" class="line"/>',
        f'<circle cx="{x(len(points) - 1):.1f}" cy="{y(vals[-1]):.1f}" r="4" class="end {state}"/>',
        f'<line class="cross" x1="0" x2="0" y1="0" y2="{h}" visibility="hidden"/>',
        "</svg>",
    ]
    return "".join(parts)


def gauge(change: float | None, threshold: float | None, state: str) -> str:
    """Size of the latest 3-month move against the signal's own usual range (tick = 95%)."""
    if change is None or not threshold:
        return ""
    ratio = min(abs(change) / threshold, 2.0)
    return (
        f'<div class="gauge" role="img" aria-label="Bewegung {ratio:.0%} des üblichen Rahmens">'
        f'<span class="fill {state if ratio >= 1 else "calm"}" style="width:{ratio * 50:.1f}%"></span>'
        '<span class="tick"></span></div>'
    )


def trend_chart(series: list[list], n: int) -> str:
    """Yearly EU values with the fitted trend of the last n years and of the n years before."""
    if len(series) < 2:
        return '<p class="nodata">Zu wenig Daten</p>'
    w, h, pad, bottom = 300, 96, 6, 16
    years = [y for y, _ in series]
    vals = [v for _, v in series]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    span = hi - lo
    lo, hi = lo - span * 0.12, hi + span * 0.12
    y0, y1 = years[0], years[-1]

    def x(yr):
        return pad + (yr - y0) * (w - 2 * pad) / max(1, y1 - y0)

    def y(v):
        return pad + (hi - v) * (h - bottom - 2 * pad) / (hi - lo)

    by_year = dict(series)
    parts = [
        (
            f'<svg class="trend" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="EU-Wert {y0} bis {y1} mit Trendlinien">'
        )
    ]
    line = " ".join(f"{x(a):.1f},{y(b):.1f}" for a, b in series)
    parts.append(f'<polyline points="{line}" class="tline"/>')
    for cls, end in (("fit-before", y1 - n), ("fit-now", y1)):
        seg = [by_year.get(a) for a in range(end - n + 1, end + 1)]
        if any(v is None for v in seg):
            continue
        b = slope(seg)
        mid_year, mid_val = end - (n - 1) / 2, sum(seg) / n
        xa, xb = end - n + 1, end
        ya, yb = mid_val + b * (xa - mid_year), mid_val + b * (xb - mid_year)
        parts.append(
            f'<line x1="{x(xa):.1f}" y1="{y(ya):.1f}" x2="{x(xb):.1f}" y2="{y(yb):.1f}" class="{cls}"/>'
        )
    for a, b in series:
        parts.append(
            f'<circle cx="{x(a):.1f}" cy="{y(b):.1f}" r="2.2" class="tdot">'
            f"<title>{a}: {num(b, digits_for(vals))}</title></circle>"
        )
    parts.append(f'<text x="{pad}" y="{h - 3}" class="axis">{y0}</text>')
    parts.append(f'<text x="{w - pad}" y="{h - 3}" class="axis" text-anchor="end">{y1}</text>')
    parts.append("</svg>")
    return "".join(parts)


def timeline_svg(timeline: list[dict], events: list[dict]) -> str:
    n = len(timeline)
    cw, top, ch = 5, 8, 26
    w = n * cw
    h = top + ch + 40
    idx = {t["month"]: i for i, t in enumerate(timeline)}
    level_cls = {0: "l0", 1: "l1", 2: "l2"}
    level_de = {0: "ruhig", 1: "eine Ebene in Bewegung", 2: "mehrere Ebenen in Bewegung"}
    parts = [
        (
            f'<svg class="timeline" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Lage nach Monat seit {timeline[0]["month"][:4]}">'
        )
    ]
    for i, t in enumerate(timeline):
        layers = ", ".join(LAYERS_DE.get(k, k) for k in t["layers"])
        tip = f"{month_de(t['month'])}: {level_de[t['level']]}"
        tip += " (neu)" if t["onset"] else ""
        tip += f" – {layers}" if layers else ""
        parts.append(
            f'<rect x="{i * cw}" y="{top}" width="{cw - 1}" height="{ch}" class="{level_cls[t["level"]]}">'
            f"<title>{_e(tip)}</title></rect>"
        )
        if t["onset"]:
            parts.append(
                f'<rect x="{i * cw}" y="{top - 6}" width="{cw - 1}" height="3" class="onset"/>'
            )
        if t["month"].endswith("-01") and int(t["month"][:4]) % 2 == 0:
            parts.append(
                f'<line x1="{i * cw}" x2="{i * cw}" y1="{top + ch}" y2="{top + ch + 5}" class="tickline"/>'
                f'<text x="{i * cw}" y="{top + ch + 16}" class="axis">{t["month"][:4]}</text>'
            )
    for ev in events:
        if ev["month"] not in idx:
            continue
        cx = idx[ev["month"]] * cw + cw / 2
        cy = top + ch + 24
        cls = {"new alarm": "ev-new", "alarm already running": "ev-run", "missed": "ev-miss"}
        parts.append(
            f'<path d="M{cx - 5},{cy + 9} L{cx},{cy} L{cx + 5},{cy + 9} Z" class="{cls[ev["status"]]}">'
            f"<title>{_e(month_de(ev['month']))}: {_e(ev['event'])} – "
            f"{_e(EVENTS_DE[ev['status']])}</title></path>"
        )
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------ page

CSS = """
/* Lagebild: status sentence first, then six layers as instrument rows, the monthly record since
   2008, the slow yearly trends, and the sources every number rests on. */
:root{
  --ground:#eef1f5; --sheet:#ffffff; --ink:#111a28; --muted:#566273; --faint:#8a95a5;
  --rule:#d4dae3; --wash:#e4e9f0; --accent:#2a4bb0; --accent-wash:rgba(42,75,176,.10);
  --calm:#7d8898; --move:#b8670a; --move-wash:rgba(184,103,10,.14); --alarm:#b42318;
  --alarm-wash:rgba(180,35,24,.12);
  --display:"Bricolage Grotesque","Avenir Next","Segoe UI",system-ui,sans-serif;
  --body:"Public Sans","Segoe UI",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,"SFMono-Regular",Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --ground:#0d131b; --sheet:#141c27; --ink:#e6ebf2; --muted:#9aa6b6; --faint:#6d7a8c;
  --rule:#273242; --wash:#1b2533; --accent:#8ea6ff; --accent-wash:rgba(142,166,255,.14);
  --calm:#77849a; --move:#f0a23b; --move-wash:rgba(240,162,59,.16); --alarm:#ff6b5e;
  --alarm-wash:rgba(255,107,94,.14); color-scheme:dark}}
:root[data-theme="dark"]{
  --ground:#0d131b; --sheet:#141c27; --ink:#e6ebf2; --muted:#9aa6b6; --faint:#6d7a8c;
  --rule:#273242; --wash:#1b2533; --accent:#8ea6ff; --accent-wash:rgba(142,166,255,.14);
  --calm:#77849a; --move:#f0a23b; --move-wash:rgba(240,162,59,.16); --alarm:#ff6b5e;
  --alarm-wash:rgba(255,107,94,.14); color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font:15px/1.55 var(--body);margin:0}
.wrap{max-width:1120px;margin:0 auto;padding-inline:20px;padding-block:28px 56px;display:grid;
  gap:28px;grid-template-columns:minmax(0,1fr)}
h1,h2,h3{font-family:var(--display);text-wrap:balance;margin:0}
.eyebrow{font:600 11px/1.2 var(--body);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
a{color:var(--accent)}
a:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

.masthead{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 24px;
  border-bottom:1px solid var(--rule);padding-bottom:14px}
.masthead .name{font:700 15px/1 var(--display);letter-spacing:.02em}
.masthead .date{color:var(--muted);font-size:13px}

.hero{display:grid;gap:18px;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);align-items:start}
.status{display:grid;gap:14px}
.status h1{font-size:clamp(28px,4.4vw,46px);line-height:1.08;font-weight:700;letter-spacing:-.01em}
.pill{display:inline-flex;align-items:center;gap:8px;font:600 12px/1 var(--body);letter-spacing:.04em;
  padding:7px 12px;border-radius:999px;width:max-content}
.pill::before{content:"";width:9px;height:9px;border-radius:50%;background:currentColor}
.pill.calm{color:var(--calm);background:var(--wash)}
.pill.move{color:var(--move);background:var(--move-wash)}
.pill.alarm{color:var(--alarm);background:var(--alarm-wash)}
.status p{margin:0;max-width:62ch;color:var(--ink)}
.status .lede{font-size:17px}
.status .note{color:var(--muted);font-size:14px}
.status .levels{font-size:15px;border-left:3px solid var(--ink);padding-left:12px}
.recent{display:flex;flex-wrap:wrap;gap:6px}
.recent span{font:500 12px/1 var(--body);padding:6px 9px;border-radius:6px;background:var(--wash);color:var(--muted)}
.recent span b{font-weight:600;color:var(--ink)}
.recent span.l1 b{color:var(--move)} .recent span.l2 b{color:var(--alarm)}

.panel{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:18px;display:grid;gap:12px}
.panel h2{font-size:16px;font-weight:600}
.layers-mini{display:grid;gap:8px;margin:0;padding:0;list-style:none}
.layers-mini li{display:flex;justify-content:space-between;gap:12px;align-items:center;font-size:14px;
  padding-bottom:8px;border-bottom:1px solid var(--rule)}
.layers-mini li:last-child{border-bottom:0;padding-bottom:0}
.layers-mini .lvl{display:block;font-size:12px;color:var(--muted)}
.dot{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);white-space:nowrap}
.dot::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--calm)}
.dot.move{color:var(--move)} .dot.move::before{background:var(--move)}
.dot.turn{color:var(--move)} .dot.turn::before{background:transparent;border:2px solid var(--move);width:6px;height:6px}

section{display:grid;gap:14px;grid-template-columns:minmax(0,1fr)}
.sechead{display:grid;gap:4px}
.sechead h2{font-size:clamp(20px,2.6vw,26px);font-weight:700}
.sechead p{margin:0;color:var(--muted);max-width:70ch;font-size:14px}

.grid{display:grid;gap:14px;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}
.layer{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:16px 16px 6px;
  display:grid;gap:4px;align-content:start}
.layer.active{border-color:var(--move);box-shadow:inset 0 3px 0 var(--move)}
.layer header{display:flex;justify-content:space-between;align-items:center;gap:10px;padding-bottom:6px}
.layer h3{font-size:17px;font-weight:600}
.sig{display:grid;grid-template-columns:minmax(0,1fr) 128px;gap:4px 14px;padding:12px 0;
  border-top:1px solid var(--rule)}
.sig .label{display:grid;gap:3px;min-width:0}
.sig .label strong{font-weight:600;font-size:14px;line-height:1.3}
.sig .value{font:600 22px/1.1 var(--body);font-variant-numeric:tabular-nums}
.sig .value small{font:500 12px var(--body);color:var(--muted);margin-left:3px}
.sig .move-txt,.sig .level-txt{font-size:12px;color:var(--muted)}
.sig .level-txt.extreme{color:var(--ink);font-weight:600}
.sig .level-txt.extreme::before{content:"";display:inline-block;width:7px;height:7px;margin-right:6px;
  transform:rotate(45deg);background:var(--ink);vertical-align:1px}
.sig .chart{grid-column:1 / -1;display:grid;gap:6px}
.sig .src{grid-column:1 / -1;font-size:11.5px;color:var(--faint);line-height:1.4}
.sig .side{display:grid;gap:6px;justify-items:end;align-content:start;text-align:right}
.gauge{position:relative;height:6px;width:100%;background:var(--wash);border-radius:3px;overflow:hidden}
.gauge .fill{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--calm)}
.gauge .fill.move{background:var(--move)}
.gauge .tick{position:absolute;left:50%;top:-2px;bottom:-2px;width:2px;background:var(--ink);opacity:.55}
.spark{width:100%;height:auto;display:block;overflow:visible}
.spark .line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.spark .area{fill:var(--accent-wash);stroke:none}
.spark .zero{stroke:var(--rule);stroke-width:1}
.spark .win{fill:var(--wash)} .spark .win.move,.spark .win.turn{fill:var(--move-wash)}
.spark .end{fill:var(--accent);stroke:var(--sheet);stroke-width:2}
.spark .end.move,.spark .end.turn{fill:var(--move)}
.spark .cross{stroke:var(--muted);stroke-width:1}
.spark-axis{display:flex;justify-content:space-between;font:11px var(--mono);color:var(--faint)}
.nodata{color:var(--faint);font-size:12px;margin:0}

.record{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:18px;display:grid;gap:14px}
.scroll{overflow-x:auto}
.timeline{width:100%;min-width:640px;height:auto;display:block}
.timeline .l0{fill:var(--wash)} .timeline .l1{fill:var(--move);opacity:.45} .timeline .l2{fill:var(--alarm)}
.timeline .onset{fill:var(--ink)}
.timeline .tickline{stroke:var(--faint);stroke-width:1}
.timeline .axis,.trend .axis{font:10px var(--mono);fill:var(--muted)}
.timeline .ev-new{fill:var(--accent)} .timeline .ev-run{fill:var(--faint)} .timeline .ev-miss{fill:none;stroke:var(--alarm);stroke-width:1.5}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;color:var(--muted);margin:0;padding:0;list-style:none}
.legend li{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:2px;display:inline-block}
.sw.l0{background:var(--wash);border:1px solid var(--rule)} .sw.l1{background:var(--move);opacity:.45} .sw.l2{background:var(--alarm)}
.tri{width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-bottom:10px solid var(--accent)}
.tri.run{border-bottom-color:var(--faint)}
.tri.miss{border-bottom-color:var(--alarm);opacity:.6}
.scores{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.score{border-top:2px solid var(--rule);padding-top:8px;display:grid;gap:2px}
.score b{font:700 26px/1 var(--display);font-variant-numeric:tabular-nums}
.score span{font-size:12.5px;color:var(--muted)}

.trends{display:grid;gap:14px;grid-template-columns:repeat(3,minmax(0,1fr))}
.tcard{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:14px 14px 12px;display:grid;gap:8px;align-content:start}
.tcard.flag{border-color:var(--move);box-shadow:inset 0 3px 0 var(--move)}
.tcard .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.tcard h3{font-size:15px;font-weight:600}
.tcard .axisname{font:600 10.5px/1 var(--body);letter-spacing:.1em;text-transform:uppercase;color:var(--faint)}
.tcard .val{font:600 20px/1 var(--body);font-variant-numeric:tabular-nums;white-space:nowrap}
.tcard .val small{font:500 11.5px var(--body);color:var(--muted);margin-left:4px}
.tcard .words{font-size:13.5px;font-weight:600}
.tcard .breadth{font-size:12.5px;color:var(--muted);margin:0}
.tcard .breadth.flag{color:var(--move);font-weight:600}
.tcard .src{font-size:11.5px;color:var(--faint)}
.trend{width:100%;height:auto;display:block}
.trend .tline{fill:none;stroke:var(--accent);stroke-width:1.6;opacity:.55}
.trend .tdot{fill:var(--accent)}
.trend .fit-now{stroke:var(--ink);stroke-width:2.4;stroke-linecap:round}
.trend .fit-before{stroke:var(--faint);stroke-width:2.4;stroke-dasharray:4 4;stroke-linecap:round}
.fitlegend{display:grid;gap:6px;font-size:12.5px;color:var(--muted)}
.tcard.guide{background:transparent;border-style:dashed}
.fitlegend i{display:inline-block;width:18px;height:0;border-top:2.4px solid var(--ink);vertical-align:middle;margin-right:6px}
.fitlegend i.before{border-top:2.4px dashed var(--faint)}

.method{display:grid;gap:14px;grid-template-columns:repeat(3,minmax(0,1fr))}
.method div{display:grid;gap:4px;align-content:start}
.method h3{font-size:15px;font-weight:600}
.method p{margin:0;font-size:13.5px;color:var(--muted)}
.tablewrap{overflow-x:auto;background:var(--sheet);border:1px solid var(--rule);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:640px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font:600 11px/1.2 var(--body);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
tr:last-child td{border-bottom:0}
td.mono{font-size:12px;white-space:nowrap}
footer{color:var(--muted);font-size:12.5px;border-top:1px solid var(--rule);padding-top:14px;display:grid;gap:6px}
footer p{margin:0;max-width:90ch}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--sheet);font:12px/1.3 var(--mono);
  padding:5px 8px;border-radius:5px;z-index:10}

@media (max-width:900px){
  .hero{grid-template-columns:minmax(0,1fr)}
  .trends{grid-template-columns:repeat(2,minmax(0,1fr))}
  .method{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:680px){
  .wrap{padding-inline:16px}
  .grid,.trends{grid-template-columns:minmax(0,1fr)}
  .scores{grid-template-columns:repeat(2,minmax(0,1fr))}
  .sig{grid-template-columns:minmax(0,1fr) 108px}
}
@media (prefers-reduced-motion:no-preference){.gauge .fill{transition:width .4s ease}}
"""

SCRIPT = """
(function(){
  var tip=document.getElementById('tip');
  document.querySelectorAll('svg.spark').forEach(function(svg){
    var pts=JSON.parse(svg.getAttribute('data-points')); var cross=svg.querySelector('.cross');
    var unit=svg.closest('.sig').getAttribute('data-unit')||'';
    function show(ev){
      var r=svg.getBoundingClientRect(); var f=(ev.clientX-r.left)/r.width;
      var i=Math.max(0,Math.min(pts.length-1,Math.round(f*(pts.length-1))));
      var vb=svg.viewBox.baseVal; var x=5+i*(vb.width-10)/(pts.length-1);
      cross.setAttribute('x1',x); cross.setAttribute('x2',x); cross.setAttribute('visibility','visible');
      var v=pts[i][1].toLocaleString('de-DE',{maximumFractionDigits:2});
      tip.textContent=pts[i][0]+': '+v+(unit?' '+unit:''); tip.hidden=false;
      tip.style.left=Math.min(ev.clientX+12,window.innerWidth-160)+'px'; tip.style.top=(ev.clientY-34)+'px';
    }
    function hide(){cross.setAttribute('visibility','hidden'); tip.hidden=true;}
    svg.addEventListener('pointermove',show); svg.addEventListener('pointerleave',hide);
  });
})();
"""


def _source_line(cards: list[str], by_card: dict[str, dict], through: str) -> str:
    bits = []
    for c in cards:
        p = by_card[c]
        when = f", abgerufen {day_de(date.fromisoformat(p['retrieved']))}" if p["retrieved"] else ""
        bits.append(f"{_e(p['provider'])} · {_e(p['datasets'])}{when}")
    return f"Quelle: {'; '.join(bits)} · Daten bis {_e(through)}"


def _signal_block(s: dict, by_card: dict[str, dict]) -> str:
    name, unit, cu = SIGNALS_DE.get(s["indicator"], (s["indicator"], "", ""))
    state, state_de = signal_state(s)
    hist = s["history"]
    d = digits_for([v for _, v in hist] or [s["value"] or 0])
    window = 1 if "-Q" in s["latest_period"] else 3
    move = (
        f"Tempo: {num(s['change'], d, True)} {cu} in drei Monaten, üblich bis ±{num(s['threshold'], d)}"
        if s["change"] is not None and s["threshold"]
        else "Tempo: zu kurze Geschichte für einen Vergleich"
    )
    if s.get("change_6m") is not None:
        move += f" · {num(s['change_6m'], d, True)} {cu} in sechs Monaten".replace("  ", " ")
    extreme = level_extreme(s)
    pseudo = " · ohne historische Datenstände" if s["knowledge"] == "pseudo" else ""
    axis = (
        f'<div class="spark-axis"><span>{_e(period_de(hist[0][0]))}</span>'
        f"<span>{_e(period_de(hist[-1][0]))}</span></div>"
        if hist
        else ""
    )
    return f"""
<div class="sig" data-unit="{_e(unit if unit not in ("Saldo", "Index") else "")}">
  <div class="label"><strong>{_e(name)}</strong><span class="dot {state}">{state_de}</span></div>
  <div class="side"><div class="value">{num(s["value"], d)}<small>{_e(unit)}</small></div></div>
  <div class="chart">{sparkline(hist, window, state)}{axis}
    {gauge(s["change"], s["threshold"], state)}<span class="move-txt">{move}</span>
    <span class="level-txt{" extreme" if extreme else ""}">{_e(level_words(s))}</span></div>
  <div class="src">{_source_line(s["sources"], by_card, period_de(s["latest_period"]))}{pseudo}</div>
</div>"""


def _trend_card(r: dict, by_card: dict[str, dict], flagged: list[int], this_year: int) -> str:
    name, unit, axis = STRUCTURAL_DE.get(r["key"], (r["label"], "", r["axis"]))
    vals = [v for _, v in r["series"]] or [r["eu_value"] or 0]
    words = trend_words(r["trend_now"], r["trend_before"], r["eu_value"], r["turn"])
    if r["unusual"]:
        lands = ", ".join(COUNTRIES_DE.get(c, c) for c in r["countries"])
        breadth = (
            f'<p class="breadth flag">Europaweit auffällig: ungewöhnliche Trendänderung in '
            f"{len(r['countries'])} von {r['members']} Staaten ({_e(lands)}).</p>"
        )
    else:
        breadth = '<p class="breadth">Keine europaweite Häufung ungewöhnlicher Trendänderungen.</p>'
    past = [y for y in flagged if y < this_year]
    if past:
        breadth += (
            f'<p class="breadth">Früher auffällig (Stand Jahresende): {_e(_years(past))}.</p>'
        )
    note = " · EU-Wert: Mittel der Mitgliedstaaten" if "mean of member" in (r["note"] or "") else ""
    return f"""
<article class="tcard{" flag" if r["unusual"] else ""}">
  <div class="top"><span class="axisname">{_e(axis)}</span><span class="val">{num(r["eu_value"], digits_for(vals))}<small>{_e(unit)}</small></span></div>
  <h3>{_e(name)}</h3>
  {trend_chart(r["series"], r["trend_years"])}
  <div class="words">{_e(words)}</div>
  {breadth}
  <div class="src">{_source_line(r["sources"], by_card, str(r["latest_year"]))}{note}</div>
</article>"""


def _years(years: list[int]) -> str:
    """[2011, 2012, 2013, 2015] -> '2011–2013, 2015'."""
    out, run = [], []
    for y in sorted(years):
        if run and y != run[-1] + 1:
            out.append(f"{run[0]}–{run[-1]}" if len(run) > 1 else str(run[0]))
            run = []
        run.append(y)
    if run:
        out.append(f"{run[0]}–{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


def _source_row(s: dict) -> str:
    link = f'<a href="{_e(s["url"])}">Dokumentation</a>' if s["url"] else ""
    return (
        f"<tr><td>{_e(s['provider'])}</td><td>{_e(s['name'])}</td>"
        f'<td class="mono">{_e(s["datasets"])}</td><td>{_e(s["licence"])}</td>'
        f'<td class="mono">{_e(s["retrieved"] or "–")}</td><td>{link}</td></tr>'
    )


def render(p: dict) -> str:
    by_card = {s["card"]: s for s in p["sources"]}
    generated = datetime.fromisoformat(p["generated_utc"]).date()
    state, title = headline(p)
    now = p["now"]
    active = [s for s in p["signals"] if s["unusual"] or s["turn"]]
    lede = " ".join(explain_signal(s) for s in active) or (
        "Alle beobachteten Signale bewegen sich im Rahmen ihrer eigenen Geschichte."
    )
    level_short = {0: "ruhig", 1: "1 Ebene", 2: "mehrere Ebenen"}
    recent = "".join(
        f'<span class="l{r["level"]}">{_e(MONTHS_DE[int(r["month"][5:]) - 1][:3])}. '
        f"<b>{level_short[r['level']]}</b></span>"
        for r in now["recent"]
    )
    by_layer: dict[str, list[dict]] = {}
    for s in p["signals"]:
        by_layer.setdefault(s["layer"], []).append(s)
    mini, cards = [], []
    for layer in p["layers"]:
        sigs = by_layer.get(layer["key"], [])
        st = (
            "move"
            if any(s["unusual"] for s in sigs)
            else "turn"
            if any(s["turn"] for s in sigs)
            else "calm"
        )
        st_de = {"move": "Tempo ungewöhnlich", "turn": "Richtungswechsel", "calm": "Tempo üblich"}[
            st
        ]
        ext = [x for x in (level_extreme(s) for s in sigs) if x]
        lvl = (
            f'<span class="lvl">Niveau {"hoch" if "hoch" in ext else "niedrig"} bei '
            f"{len(ext)} von {len(sigs)}</span>"
            if ext
            else ""
        )
        name = LAYERS_DE.get(layer["key"], layer["label"])
        on = layer["key"] in now["active_layers"]
        mini.append(f'<li><span>{_e(name)}{lvl}</span><span class="dot {st}">{st_de}</span></li>')
        cards.append(
            f'<article class="layer{" active" if on else ""}"><header><h3>{_e(name)}</h3>'
            f'<span class="dot {st}">{st_de}</span></header>'
            + "".join(_signal_block(s, by_card) for s in sigs)
            + "</article>"
        )
    t = p["test"]
    ev = t["events"]
    n_new = sum(e["status"] == "new alarm" for e in ev)
    n_run = sum(e["status"] == "alarm already running" for e in ev)
    n_miss = sum(e["status"] == "missed" for e in ev)
    first_year = p["timeline"][0]["month"][:4]
    flagged = [r for r in p["structural"] if r["unusual"]]
    slow_line = (
        "Bei den langsamen Trends fällt europaweit auf: "
        + ", ".join(
            f"{STRUCTURAL_DE.get(r['key'], (r['label'],))[0]} "
            f"({trend_words(r['trend_now'], r['trend_before'], r['eu_value'], r['turn'])})"
            for r in flagged
        )
        + "."
        if flagged
        else "Bei den langsamen Trends gibt es derzeit keine europaweite Häufung."
    )
    extremes = [s for s in p["signals"] if level_extreme(s)]
    level_line = (
        "Ungewöhnliches Niveau bei üblichem Tempo. "
        + "; ".join(
            f"{SIGNALS_DE.get(s['indicator'], (s['indicator'],))[0]}: "
            f"{level_words(s).removeprefix('Niveau: ')}"
            for s in extremes
            if not (s["unusual"] or s["turn"])
        )
        + "."
        if any(not (s["unusual"] or s["turn"]) for s in extremes)
        else ""
    )
    trends = "".join(
        _trend_card(r, by_card, p["structural_flagged_years"].get(r["key"], []), generated.year)
        for r in p["structural"]
    )
    rows = "".join(_source_row(s) for s in p["sources"])
    return f"""<title>Lagebild Europa</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=JetBrains+Mono:wght@400;500;600&family=Public+Sans:wght@400;500;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header class="masthead">
  <span class="name">Lagebild Europa</span>
  <span class="date">Stand {day_de(generated)} · Euroraum und EU</span>
</header>

<div class="hero">
  <div class="status">
    <span class="pill {state}">{_e({"calm": "Ruhig", "move": "In Bewegung", "alarm": "Mehrere Ebenen"}[state])}</span>
    <h1>{_e(title)}</h1>
    <p class="lede">{_e(lede)}</p>
    {f'<p class="levels">{_e(level_line)}</p>' if level_line else ""}
    <p class="note">{_e(slow_line)} Das Lagebild sagt nichts voraus. Es zeigt, wo sich gerade
    mehr bewegt als üblich, gemessen an der eigenen Geschichte jedes Signals.</p>
    <div class="recent" aria-label="Letzte Monate">{recent}</div>
  </div>
  <aside class="panel" aria-label="Sechs Ebenen auf einen Blick">
    <h2>Sechs Ebenen auf einen Blick</h2>
    <ul class="layers-mini">{"".join(mini)}</ul>
  </aside>
</div>

<section>
  <div class="sechead"><span class="eyebrow">Monatlich</span><h2>Was sich gerade bewegt</h2>
  <p>Zwei Fragen pro Signal. <b>Tempo:</b> Der Balken misst die Bewegung der letzten drei Monate
  an den bisherigen Bewegungen desselben Signals; erreicht er die Markierung, war sie größer als in
  95 von 100 früheren Fällen. Ein Richtungswechsel heißt: Nach einer längeren Bewegung kehrt sich
  die Sechs-Monats-Änderung deutlich um. <b>Niveau:</b> Wo der aktuelle Wert in der gesamten
  Geschichte des Signals liegt. Ein hohes Niveau bei üblichem Tempo heißt: Der Schock ist da, aber
  er wächst gerade nicht weiter. Nur das Tempo löst Alarme aus. Die Kurven zeigen fünf Jahre; Tempo und Niveau werden an der gesamten Geschichte gemessen.</p></div>
  <div class="grid">{"".join(cards)}</div>
</section>

<section class="record">
  <div class="sechead"><span class="eyebrow">Rückblick seit {first_year}</span><h2>Wann sich Europa zuletzt bewegte</h2>
  <p>Ein Monat zählt als Alarm, wenn sich mindestens zwei Ebenen zugleich ungewöhnlich bewegen.
  Die Dreiecke markieren Wendepunkte, die vor der ersten Auswertung festgelegt wurden.</p></div>
  <div class="scroll">{timeline_svg(p["timeline"], p["events"])}</div>
  <ul class="legend">
    <li><span class="sw l0"></span>ruhig</li><li><span class="sw l1"></span>eine Ebene</li>
    <li><span class="sw l2"></span>mehrere Ebenen (Alarm)</li>
    <li><span class="tri"></span>Wendepunkt neu erkannt</li>
    <li><span class="tri run"></span>Alarm lief bereits</li><li><span class="tri miss"></span>verpasst</li>
  </ul>
  <div class="scores">
    <div class="score"><b>{n_new} von {len(ev)}</b><span>Wendepunkten mit neuem Alarm erkannt</span></div>
    <div class="score"><b>{n_run}</b><span>fielen in eine bereits laufende Alarmphase</span></div>
    <div class="score"><b>{n_miss}</b><span>verpasst</span></div>
    <div class="score"><b>{len(t["false_alarms"])}</b><span>Alarme ohne passendes Ereignis</span></div>
  </div>
</section>

<section>
  <div class="sechead"><span class="eyebrow">Jährlich · 27 Mitgliedstaaten</span><h2>Die langsamen Trends</h2>
  <p>Für jedes Land wird der Trend der letzten fünf Jahre mit dem der fünf Jahre davor verglichen.
  Europaweit auffällig ist ein Thema erst, wenn ungewöhnlich viele Länder zugleich in dieselbe
  Richtung umschwenken. Feste Schwellenwerte gibt es nicht.</p>
</div>
  <div class="trends">{trends}{GUIDE_CARD}</div>
</section>

<section>
  <div class="sechead"><span class="eyebrow">Methode</span><h2>So entsteht das Lagebild</h2></div>
  <div class="method">
    <div><h3>Nur amtliche Quellen</h3><p>Alle Zahlen stammen von EZB, Eurostat, OECD und Weltbank.
    Jede Datei wird beim Abruf unverändert archiviert. Jede Zahl auf dieser Seite lässt sich auf
    Datensatz und Abrufdatum zurückführen.</p></div>
    <div><h3>Gemessen an der eigenen Geschichte</h3><p>Ein Signal gilt als ungewöhnlich, wenn
    seine Bewegung größer ist als 95 % seiner bisherigen Bewegungen. Wo es Datenstände gibt, wird
    nur verwendet, was zum jeweiligen Zeitpunkt bekannt war.</p></div>
    <div><h3>Keine Prognose</h3><p>Das Lagebild zeigt, dass sich etwas bewegt, nicht wohin es
    führt. Umfragen, Handel, Gas und Asyl haben keine historischen Datenstände; für sie nutzt der
    Rückblick heutige Werte mit Veröffentlichungsverzögerung.</p></div>
  </div>
</section>

<section>
  <div class="sechead"><span class="eyebrow">Quellen</span><h2>Woher die Daten kommen</h2></div>
  <div class="tablewrap"><table>
    <thead><tr><th>Herausgeber</th><th>Datensatz</th><th>Code</th><th>Lizenz</th><th>Abruf</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</section>

<footer>
  <p>Lagebild Europa, Modellversion {_e(p["model_version"])}, erzeugt am {day_de(generated)} aus den
  archivierten Rohdaten. Daten: © Europäische Zentralbank, © Europäische Union (Eurostat),
  © OECD, © Weltbank, jeweils unter den genannten Lizenzen.</p>
</footer>
</div>
<div id="tip" hidden></div>
<script>{SCRIPT}</script>
"""


GUIDE_CARD = """
<article class="tcard guide">
  <span class="axisname">Lesehilfe</span>
  <h3>So lesen Sie die Karten</h3>
  <div class="fitlegend"><span><i></i>Trend der letzten fünf Jahre</span>
  <span><i class="before"></i>Trend der fünf Jahre davor</span></div>
  <p class="breadth">Punkte: EU-Wert je Jahr. Weichen die beiden Linien deutlich voneinander ab,
  hat sich der Trend geändert.</p>
  <p class="breadth">Eine orange Karte heißt: In ungewöhnlich vielen Mitgliedstaaten hat sich der
  Trend zugleich in dieselbe Richtung verschoben, mehr als in 95 % der vergangenen 15 Jahre.</p>
  <p class="breadth">Jahresdaten erscheinen spät. Die Karte nennt das letzte verfügbare Jahr.</p>
</article>"""


def write(conn: psycopg.Connection, label: str | None = None) -> Path:
    payload = build_payload(conn, label)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    page = OUT_DIR / "index.html"
    page.write_text(render(payload), encoding="utf-8")
    return page


def main(argv: list[str]) -> int:
    with connect() as conn:
        page = write(conn, argv[0] if argv else None)
    print(f"wrote {page.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
