"""Newsletter dashboard: the current situation in Europe on one page, in German.

The page describes; it does not judge. There are no thresholds and no labels such as "calm" or
"unusual". Every number is shown against its own history: where the latest value stands among
all earlier values, and how large the latest move is compared with all earlier moves. The reader
sees the distributions and decides what matters. The detector's alarm rule stays in the
repository as a test instrument and does not appear here.

Every number carries the source card, dataset code and retrieval date it rests on.

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
from srm.detect import config as detector_config
from srm.detect import version_id
from srm.indicators import indicator_series
from srm.model_content import current_label
from srm.structural import config as structural_config
from srm.structural import eu_series, known_year, load_panel, slope, trend_at

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "reports" / "dashboard"
DISPLAY_YEARS = 5  # sparklines only; every measure uses the full history
STRUCTURAL_YEARS = 20
RECORD_START = "2008-01"
MIN_HISTORY = {"M": 60, "Q": 20}  # earlier moves needed before a move is placed in its history
HIST_BINS = 32

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

# key -> (German name, unit of the level, axis, unit of the yearly trend)
STRUCTURAL_DE = {
    "rule_of_law": ("Rechtsstaatlichkeit", "Weltbank-Index", "Regierungsführung", "Punkte"),
    "voice_accountability": (
        "Mitsprache und Rechenschaft",
        "Weltbank-Index",
        "Regierungsführung",
        "Punkte",
    ),
    "corruption_perceptions": (
        "Korruptionswahrnehmung (höher = sauberer)",
        "Punkte",
        "Regierungsführung",
        "Punkte",
    ),
    "income_inequality": ("Einkommensungleichheit", "S80/S20", "Zusammenhalt", ""),
    "gov_expenditure": ("Staatsausgaben", "% des BIP", "Wirtschaftsordnung", "Pp."),
    "old_age_dependency": ("Altenquotient", "65+ je 100 im Alter 15–64", "Demografie", ""),
    "fertility": ("Geburtenrate", "Kinder je Frau", "Demografie", "Kinder je Frau"),
    "rd_intensity": ("Forschungsausgaben", "% des BIP", "Technologie", "Pp."),
    "climate_losses": ("Schäden durch Klimaextreme", "€ je Einwohner", "Klima", "€"),
    "energy_import_dependency": ("Energieimportabhängigkeit", "%", "Energie", "Pp."),
    "gov_debt": ("Staatsschulden", "% des BIP", "Staatsfinanzen", "Pp."),
}

EVENTS_TEXT_DE = {
    "2008-09": "Lehman-Pleite, globale Finanzkrise",
    "2011-07": "Euro-Schuldenkrise erfasst Italien und Spanien",
    "2014-06": "EZB führt den Negativzins ein, Deflationssorgen",
    "2015-09": "Höhepunkt der Fluchtbewegung in die EU",
    "2020-03": "Pandemie und Lockdowns",
    "2021-07": "Beginn des Inflationsschubs",
    "2022-02": "Russlands Angriff auf die Ukraine, Energieschock",
    "2022-07": "Erste EZB-Zinserhöhung seit elf Jahren",
    "2023-09": "Letzte EZB-Zinserhöhung, Zinsgipfel",
    "2024-06": "Erste EZB-Zinssenkung des Lockerungszyklus",
    "2026-03": "Krieg im Nahen Osten, neuer Energiepreisschock",
}

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


def pct(share: float) -> str:
    return f"{round(100 * share)} %"


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


# ------------------------------------------------------------------ measures


def freq_of(label: str) -> str:
    return "Q" if "-Q" in label else "M"


def months_of(label: str) -> list[str]:
    """'2008-Q3' -> ['2008-07', '2008-08', '2008-09']; '2008-07' -> ['2008-07']."""
    if "-Q" in label:
        y, q = label.split("-Q")
        first = 3 * (int(q) - 1) + 1
        return [f"{y}-{m:02d}" for m in range(first, first + 3)]
    return [label]


def share_below(x: float, past: list[float]) -> float:
    return sum(v < x for v in past) / len(past)


def changes_of(pts: list, step: int) -> list[tuple[str, float]]:
    return [(pts[i][1], pts[i][2] - pts[i - step][2]) for i in range(step, len(pts))]


def move_ranks(pts: list) -> dict[str, float]:
    """For each period: share of all earlier moves (absolute size) smaller than this move.
    A move is the change over three months (one quarter for quarterly series)."""
    if not pts:
        return {}
    f = freq_of(pts[-1][1])
    changes = changes_of(pts, 1 if f == "Q" else 3)
    out, past = {}, []
    for label, c in changes:
        if len(past) >= MIN_HISTORY[f]:
            out[label] = round(share_below(abs(c), past), 4)
        past.append(abs(c))
    return out


def signal_stats(pts: list) -> dict:
    """Latest value and move, each placed in the full history of the series."""
    f = freq_of(pts[-1][1])
    step = 1 if f == "Q" else 3
    vals = [p[2] for p in pts]
    changes = changes_of(pts, step)
    out = {
        "freq": f,
        "value": vals[-1],
        "latest_period": pts[-1][1],
        "since": pts[0][1][:4],
        "levels": [round(v, 3) for v in vals],
        "changes": [round(c, 3) for _, c in changes],
        "change": changes[-1][1] if changes else None,
        "change_6m": vals[-1] - vals[-1 - 2 * step] if len(vals) > 2 * step else None,
        "level_rank": share_below(vals[-1], vals[:-1]) if len(vals) > 24 else None,
        "move_rank": None,
    }
    if len(changes) > MIN_HISTORY[f]:
        out["move_rank"] = share_below(abs(changes[-1][1]), [abs(c) for _, c in changes[:-1]])
    return out


def record(signals: list[dict], layers: list[str], end_month: str) -> dict:
    """Per layer and month: the largest move rank among the layer's signals, and which signal."""
    months = []
    y, m = int(RECORD_START[:4]), int(RECORD_START[5:])
    while f"{y}-{m:02d}" <= end_month:
        months.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    rows = {}
    for layer in layers:
        best: dict[str, tuple[float, str]] = {}
        for s in signals:
            if s["layer"] != layer:
                continue
            for label, r in s["move_ranks"].items():
                for mo in months_of(label):
                    if mo not in best or r > best[mo][0]:
                        best[mo] = (r, s["indicator"])
        rows[layer] = [best.get(mo) for mo in months]
    return {"months": months, "rows": rows}


# ------------------------------------------------------------------ data


def provenance_for_families(conn: psycopg.Connection, families: list[str]) -> list[dict]:
    rows = conn.execute(
        """SELECT sc.card_id, sc.provider, sc.name,
                  string_agg(DISTINCT d.dataset_id, ', ') FILTER (WHERE EXISTS (
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


def structural_entry(conn, ind: dict, cfg: dict, at: datetime) -> dict:
    n = cfg["trend_years"]
    panel = load_panel(conn, ind["family"], ind["match"])
    members, agg, note = eu_series(
        panel, ind, cfg["aggregate"], known_year(at, ind.get("lag_months", 9))
    )
    out = {"key": ind["key"], "axis": ind["axis"], "note": note, "trend_years": n, "members": 0}
    if not agg:
        return out | {"series": [], "latest_year": None}
    t = max(agg)
    slopes_now = [trend_at(s, t, n) for s in members.values()]
    slopes_before = [trend_at(s, t - n, n) for s in members.values()]
    return out | {
        "series": [[y, round(agg[y], 4)] for y in sorted(agg) if y > t - STRUCTURAL_YEARS],
        "latest_year": t,
        "eu_value": round(agg[t], 4),
        "trend_now": trend_at(agg, t, n),
        "trend_before": trend_at(agg, t - n, n),
        "members": sum(a is not None for a in slopes_now),
        "rising_now": sum(a is not None and a > 0 for a in slopes_now),
        "falling_now": sum(a is not None and a < 0 for a in slopes_now),
        "members_before": sum(b is not None for b in slopes_before),
        "rising_before": sum(b is not None and b > 0 for b in slopes_before),
        "falling_before": sum(b is not None and b < 0 for b in slopes_before),
    }


def load_events() -> list[dict]:
    import yaml

    data = yaml.safe_load((ROOT / "model" / "events.yaml").read_text(encoding="utf-8"))
    return [
        {"month": str(e["month"]), "text": EVENTS_TEXT_DE.get(str(e["month"]), e["label"])}
        for e in data["events"]
    ]


def build_payload(conn: psycopg.Connection, label: str | None = None) -> dict:
    label = label or current_label()
    mv = version_id(conn, label)
    at = datetime.now(UTC)
    sources: dict[str, dict] = {}

    def remember(provs: list[dict]) -> list[str]:
        for p in provs:
            sources.setdefault(p["card"], p)
        return [p["card"] for p in provs]

    cfg = detector_config(label)
    start = date(at.year - DISPLAY_YEARS, at.month, 1)
    signals = []
    for layer in cfg["layers"]:
        for sig in layer["signals"]:
            pts = indicator_series(conn, sig["indicator"], at, mv)
            if not pts:
                continue
            provs = provenance_for_families(
                conn, indicator_families(conn, sig["indicator"], mv, at)
            )
            signals.append(
                {
                    "layer": layer["key"],
                    "indicator": sig["indicator"],
                    "knowledge": sig["knowledge"],
                    **signal_stats(pts),
                    "move_ranks": move_ranks(pts),
                    "history": [[p[1], round(p[2], 4)] for p in pts if p[0] >= start],
                    "sources": remember(provs),
                }
            )
    layers = [layer["key"] for layer in cfg["layers"]]
    scfg = structural_config(label)
    structural = []
    for ind in scfg["indicators"]:
        entry = structural_entry(conn, ind, scfg, at)
        entry["sources"] = remember(provenance_for_families(conn, [ind["family"]]))
        structural.append(entry)
    return {
        "model_version": label,
        "generated_utc": at.isoformat(),
        "layers": layers,
        "signals": signals,
        "record": record(signals, layers, at.strftime("%Y-%m")),
        "events": load_events(),
        "structural": structural,
        "sources": sorted(sources.values(), key=lambda p: (p["provider"], p["card"])),
    }


# ------------------------------------------------------------------ wording


def level_sentence(s: dict) -> str:
    unit = "Quartale" if s["freq"] == "Q" else "Monate"
    r = s["level_rank"]
    if r is None:
        return "Zu kurze Geschichte für eine Einordnung."
    if r >= 0.5:
        return f"Höher als in {pct(r)} aller {unit} seit {s['since']}."
    return f"Niedriger als in {pct(1 - r)} aller {unit} seit {s['since']}."


def move_sentence(s: dict, cu: str) -> str:
    span = "einem Quartal" if s["freq"] == "Q" else "drei Monaten"
    what = "Quartalsbewegungen" if s["freq"] == "Q" else "Drei-Monats-Bewegungen"
    d = digits_for(s["levels"])
    head = f"{num(s['change'], d, True)} {cu} in {span}".replace("  ", " ")
    if s["move_rank"] is None:
        return f"{head}. Zu kurze Geschichte für eine Einordnung."
    return f"{head}: größer als {pct(s['move_rank'])} aller bisherigen {what} seit {s['since']}."


def name_of(s: dict) -> str:
    return SIGNALS_DE.get(s["indicator"], (s["indicator"],))[0]


def top_moves(signals: list[dict], n: int = 3) -> list[dict]:
    return sorted(
        (s for s in signals if s["move_rank"] is not None), key=lambda s: -s["move_rank"]
    )[:n]


def top_levels(signals: list[dict], n: int = 3) -> list[dict]:
    return sorted(
        (s for s in signals if s["level_rank"] is not None),
        key=lambda s: -abs(s["level_rank"] - 0.5),
    )[:n]


def trend_sentence(r: dict) -> str:
    unit = STRUCTURAL_DE.get(r["key"], ("", "", "", ""))[3]
    if r.get("trend_now") is None or r.get("trend_before") is None:
        return "EU-Trend nicht bestimmbar: Die EU-Reihe hat Lücken."
    d = 3 if max(abs(r["trend_now"]), abs(r["trend_before"])) < 0.1 else 2
    u = f" {unit}" if unit else ""

    def signed(v: float) -> str:
        return num(0.0, d) if round(v, d) == 0 else num(v, d, True)

    return (
        f"EU-Trend jetzt {signed(r['trend_now'])}{u} pro Jahr, "
        f"in den fünf Jahren davor {signed(r['trend_before'])}{u} pro Jahr."
    )


def breadth_sentence(r: dict) -> str:
    if not r.get("members"):
        return ""
    up = (r.get("trend_now") or 0) >= 0
    now = r["rising_now"] if up else r["falling_now"]
    before = r["rising_before"] if up else r["falling_before"]
    word = "Steigender" if up else "Fallender"
    tail = (
        f", in den fünf Jahren davor in {before} von {r['members_before']}"
        if r["members_before"]
        else ""
    )
    return f"{word} Trend in {now} von {r['members']} Mitgliedstaaten{tail}."


# ------------------------------------------------------------------ drawing


def sparkline(points: list[list], window: int) -> str:
    """History as a line with area fill; the last `window` points sit on a grey band."""
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
    base = y(0) if lo < 0 < hi else h - pad
    area = f"{x(0):.1f},{base:.1f} {line} {x(len(points) - 1):.1f},{base:.1f}"
    k = max(0, len(points) - 1 - window)
    parts = [
        (
            f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Verlauf {points[0][0]} bis {points[-1][0]}" '
            f"data-points='{_e(json.dumps(points))}'>"
        ),
        f'<rect x="{x(k):.1f}" y="0" width="{w - pad - x(k):.1f}" height="{h}" class="win"/>',
    ]
    if lo < 0 < hi:
        parts.append(
            f'<line x1="{pad}" x2="{w - pad}" y1="{base:.1f}" y2="{base:.1f}" class="zero"/>'
        )
    parts += [
        f'<polygon points="{area}" class="area"/>',
        f'<polyline points="{line}" class="line"/>',
        f'<circle cx="{x(len(points) - 1):.1f}" cy="{y(vals[-1]):.1f}" r="4" class="end"/>',
        f'<line class="cross" x1="0" x2="0" y1="0" y2="{h}" visibility="hidden"/>',
        "</svg>",
    ]
    return "".join(parts)


def histogram(values: list[float], current: float | None, label: str, zero: bool = False) -> str:
    """Distribution of all earlier values as bars; the current value as a marked line."""
    if len(values) < 2 or current is None:
        return ""
    w, h, pad = 560, 40, 2
    lo, hi = min([*values, current]), max([*values, current])
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    width = (hi - lo) / HIST_BINS
    counts = [0] * HIST_BINS
    for v in values:
        counts[min(HIST_BINS - 1, int((v - lo) / width))] += 1
    top = max(counts)
    bw = (w - 2 * pad) / HIST_BINS

    def x(v):
        return pad + (v - lo) / (hi - lo) * (w - 2 * pad)

    parts = [f'<svg class="hist" viewBox="0 0 {w} {h + 14}" role="img" aria-label="{_e(label)}">']
    for i, c in enumerate(counts):
        if c:
            bh = max(1.5, (h - 6) * c / top)
            parts.append(
                f'<rect x="{pad + i * bw + 0.5:.1f}" y="{h - bh:.1f}" width="{bw - 1:.1f}" '
                f'height="{bh:.1f}" class="bar"/>'
            )
    if zero and lo < 0 < hi:
        parts.append(f'<line x1="{x(0):.1f}" x2="{x(0):.1f}" y1="0" y2="{h}" class="zero"/>')
    cx = x(current)
    parts.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="0" y2="{h}" class="now"/>')
    parts.append(f'<circle cx="{cx:.1f}" cy="3" r="3.5" class="now-dot"/>')
    d = digits_for(values)
    parts.append(f'<text x="{pad}" y="{h + 12}" class="axis">{num(lo, d)}</text>')
    parts.append(
        f'<text x="{w - pad}" y="{h + 12}" class="axis" text-anchor="end">{num(hi, d)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def rank_bar(share: float) -> str:
    return (
        f'<span class="rbar" role="img" aria-label="{pct(share)}">'
        f'<span style="width:{100 * share:.1f}%"></span></span>'
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


def heat_opacity(share: float) -> float:
    """Continuous colour scale: small moves nearly invisible, the largest moves dark."""
    return round(share**4, 3)


def record_svg(rec: dict, events: list[dict]) -> str:
    months = rec["months"]
    cw, rh, left, top = 5, 18, 212, 4
    rows = list(rec["rows"])
    h_rows = top + len(rows) * (rh + 3)
    w = left + len(months) * cw
    h = h_rows + 46
    idx = {m: i for i, m in enumerate(months)}
    parts = [
        (
            f'<svg class="record-svg" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Größte Bewegung je Ebene und Monat seit {months[0][:4]}">'
        )
    ]
    for r, layer in enumerate(rows):
        y = top + r * (rh + 3)
        parts.append(
            f'<text x="0" y="{y + rh - 5}" class="rowlabel">{_e(LAYERS_DE.get(layer, layer))}</text>'
        )
        parts.append(
            f'<rect x="{left}" y="{y}" width="{len(months) * cw}" height="{rh}" class="rowbg"/>'
        )
        for i, cell in enumerate(rec["rows"][layer]):
            if cell is None:
                continue
            share, ind = cell
            op = heat_opacity(share)
            if op < 0.01:
                continue
            tip = (
                f"{month_de(months[i])} · {LAYERS_DE.get(layer, layer)}: "
                f"{name_of({'indicator': ind})}, größer als {pct(share)} der bisherigen Bewegungen"
            )
            parts.append(
                f'<rect x="{left + i * cw}" y="{y}" width="{cw - 0.6}" height="{rh}" '
                f'class="cell" fill-opacity="{op}"><title>{_e(tip)}</title></rect>'
            )
    for i, m in enumerate(months):
        if m.endswith("-01") and int(m[:4]) % 2 == 0:
            x = left + i * cw
            parts.append(
                f'<line x1="{x}" x2="{x}" y1="{h_rows}" y2="{h_rows + 5}" class="tickline"/>'
                f'<text x="{x}" y="{h_rows + 16}" class="axis">{m[:4]}</text>'
            )
    for k, ev in enumerate(events, start=1):
        if ev["month"] not in idx:
            continue
        cx = left + idx[ev["month"]] * cw + cw / 2
        cy = h_rows + 22
        parts.append(
            f'<path d="M{cx - 5},{cy + 9} L{cx},{cy} L{cx + 5},{cy + 9} Z" class="ev">'
            f"<title>{_e(month_de(ev['month']))}: {_e(ev['text'])}</title></path>"
            f'<text x="{cx}" y="{cy + 20}" class="evnum" text-anchor="middle">{k}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------ page

CSS = """
/* Lagebild: a description, not a verdict. The largest moves and the most unusual levels first,
   then each layer with its signals drawn against their own history, the record since 2008,
   the slow yearly trends, and the sources every number rests on. */
:root{
  --ground:#eef1f5; --sheet:#ffffff; --ink:#111a28; --muted:#566273; --faint:#8a95a5;
  --rule:#d4dae3; --wash:#e6eaf0; --bar:#b9c2ce; --accent:#2a4bb0; --accent-wash:rgba(42,75,176,.10);
  --display:"Bricolage Grotesque","Avenir Next","Segoe UI",system-ui,sans-serif;
  --body:"Public Sans","Segoe UI",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,"SFMono-Regular",Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --ground:#0d131b; --sheet:#141c27; --ink:#e6ebf2; --muted:#9aa6b6; --faint:#6d7a8c;
  --rule:#273242; --wash:#1d2735; --bar:#3a4657; --accent:#8ea6ff; --accent-wash:rgba(142,166,255,.14);
  color-scheme:dark}}
:root[data-theme="dark"]{
  --ground:#0d131b; --sheet:#141c27; --ink:#e6ebf2; --muted:#9aa6b6; --faint:#6d7a8c;
  --rule:#273242; --wash:#1d2735; --bar:#3a4657; --accent:#8ea6ff; --accent-wash:rgba(142,166,255,.14);
  color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font:15px/1.55 var(--body);margin:0}
.wrap{max-width:1120px;margin:0 auto;padding-inline:20px;padding-block:28px 56px;display:grid;
  gap:30px;grid-template-columns:minmax(0,1fr)}
h1,h2,h3{font-family:var(--display);text-wrap:balance;margin:0}
.eyebrow{font:600 11px/1.2 var(--body);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
a{color:var(--accent)}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

.masthead{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 24px;
  border-bottom:1px solid var(--rule);padding-bottom:14px}
.masthead .name{font:700 15px/1 var(--display);letter-spacing:.02em}
.masthead .date{color:var(--muted);font-size:13px}

.hero{display:grid;gap:18px}
.hero h1{font-size:clamp(30px,4.6vw,48px);line-height:1.06;font-weight:700;letter-spacing:-.01em}
.hero .lede{margin:0;max-width:68ch;font-size:16.5px;color:var(--muted)}
.ranks{display:grid;gap:14px;grid-template-columns:repeat(2,minmax(0,1fr))}
.panel{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:18px;display:grid;gap:10px;align-content:start}
.panel h2{font-size:16px;font-weight:600}
.panel .hint{margin:0;font-size:12.5px;color:var(--muted)}
.rank{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.rank li{display:grid;gap:4px}
.rank .top{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.rank .top strong{font-weight:600;font-size:14.5px}
.rank .top span{font:600 14px var(--body);font-variant-numeric:tabular-nums;white-space:nowrap}
.rank .sub{font-size:12.5px;color:var(--muted)}
.rbar{display:block;height:6px;background:var(--wash);border-radius:3px;overflow:hidden}
.rbar span{display:block;height:100%;background:var(--accent);border-radius:3px}

section{display:grid;gap:14px;grid-template-columns:minmax(0,1fr)}
.sechead{display:grid;gap:6px}
.sechead h2{font-size:clamp(20px,2.6vw,26px);font-weight:700}
.sechead p{margin:0;color:var(--muted);max-width:74ch;font-size:14px}
.sechead p b{color:var(--ink);font-weight:600}

.grid{display:grid;gap:14px;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}
.layer{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:16px 16px 6px;
  display:grid;gap:4px;align-content:start}
.layer h3{font-size:17px;font-weight:600;padding-bottom:6px}
.sig{display:grid;gap:8px;padding:14px 0;border-top:1px solid var(--rule)}
.sig .head{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.sig .head strong{font-weight:600;font-size:14px;line-height:1.3}
.sig .value{font:600 22px/1.1 var(--body);font-variant-numeric:tabular-nums;white-space:nowrap}
.sig .value small{font:500 12px var(--body);color:var(--muted);margin-left:3px}
.sig .part{display:grid;gap:2px}
.sig .cap{font-size:12.5px;color:var(--ink)}
.sig .cap b{font-weight:600}
.sig .src{font-size:11.5px;color:var(--faint);line-height:1.4}
.spark{width:100%;height:auto;display:block;overflow:visible}
.spark .line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.spark .area{fill:var(--accent-wash);stroke:none}
.spark .zero,.hist .zero{stroke:var(--faint);stroke-width:1;stroke-dasharray:3 3}
.spark .win{fill:var(--wash)}
.spark .end{fill:var(--accent);stroke:var(--sheet);stroke-width:2}
.spark .cross{stroke:var(--muted);stroke-width:1}
.spark-axis{display:flex;justify-content:space-between;font:11px var(--mono);color:var(--faint)}
.hist{width:100%;height:auto;display:block}
.hist .bar{fill:var(--bar)}
.hist .now{stroke:var(--accent);stroke-width:2.5}
.hist .now-dot{fill:var(--accent)}
.hist .axis,.trend .axis,.record-svg .axis{font:10px var(--mono);fill:var(--muted)}
.nodata{color:var(--faint);font-size:12px;margin:0}

.record{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:18px;display:grid;gap:14px}
.scroll{overflow-x:auto}
.record-svg{width:100%;min-width:760px;height:auto;display:block}
.record-svg .rowlabel{font:12px var(--body);fill:var(--ink)}
.record-svg .rowbg{fill:var(--wash)}
.record-svg .cell{fill:var(--accent)}
.record-svg .tickline{stroke:var(--faint);stroke-width:1}
.record-svg .ev{fill:var(--ink)}
.record-svg .evnum{font:600 10px var(--body);fill:var(--muted)}
.scale{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--muted);flex-wrap:wrap}
.scale .grad{width:220px;max-width:60vw;height:10px;border-radius:2px;border:1px solid var(--rule);
  background:linear-gradient(90deg,
    color-mix(in srgb,var(--accent) 0%,transparent) 0%,
    color-mix(in srgb,var(--accent) 6%,transparent) 50%,
    color-mix(in srgb,var(--accent) 24%,transparent) 70%,
    color-mix(in srgb,var(--accent) 41%,transparent) 80%,
    color-mix(in srgb,var(--accent) 66%,transparent) 90%,
    var(--accent) 100%)}
.events{list-style:none;margin:0;padding:0;display:grid;gap:4px 18px;grid-template-columns:repeat(2,minmax(0,1fr));font-size:12.5px;color:var(--muted)}
.events b{color:var(--ink);font-weight:600;margin-right:6px}

.trends{display:grid;gap:14px;grid-template-columns:repeat(3,minmax(0,1fr))}
.tcard{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:14px 14px 12px;display:grid;gap:8px;align-content:start}
.tcard .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.tcard h3{font-size:15px;font-weight:600}
.tcard .axisname{font:600 10.5px/1 var(--body);letter-spacing:.1em;text-transform:uppercase;color:var(--faint)}
.tcard .val{font:600 20px/1 var(--body);font-variant-numeric:tabular-nums;white-space:nowrap}
.tcard .val small{font:500 11.5px var(--body);color:var(--muted);margin-left:4px}
.tcard p{margin:0;font-size:12.5px;color:var(--muted)}
.tcard p.lead{color:var(--ink)}
.tcard .src{font-size:11.5px;color:var(--faint)}
.tcard.guide{background:transparent;border-style:dashed}
.trend{width:100%;height:auto;display:block}
.trend .tline{fill:none;stroke:var(--accent);stroke-width:1.6;opacity:.55}
.trend .tdot{fill:var(--accent)}
.trend .fit-now{stroke:var(--ink);stroke-width:2.4;stroke-linecap:round}
.trend .fit-before{stroke:var(--faint);stroke-width:2.4;stroke-dasharray:4 4;stroke-linecap:round}
.fitlegend{display:grid;gap:6px;font-size:12.5px;color:var(--muted)}
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
td.mono{font:12px var(--mono);white-space:nowrap}
footer{color:var(--muted);font-size:12.5px;border-top:1px solid var(--rule);padding-top:14px;display:grid;gap:6px}
footer p{margin:0;max-width:90ch}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--sheet);font:12px/1.3 var(--mono);
  padding:5px 8px;border-radius:5px;z-index:10}

@media (max-width:900px){
  .trends{grid-template-columns:repeat(2,minmax(0,1fr))}
  .method{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:680px){
  .wrap{padding-inline:16px}
  .grid,.trends,.ranks,.events{grid-template-columns:minmax(0,1fr)}
}
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
    d = digits_for(s["levels"])
    window = 1 if s["freq"] == "Q" else 3
    hist = s["history"]
    axis = (
        f'<div class="spark-axis"><span>{_e(period_de(hist[0][0]))}</span>'
        f"<span>{_e(period_de(hist[-1][0]))}</span></div>"
        if hist
        else ""
    )
    six = (
        f" In sechs Monaten: {num(s['change_6m'], d, True)} {cu}".rstrip(" .") + "."
        if s["change_6m"] is not None and s["freq"] == "M"
        else ""
    )
    pseudo = " · ohne historische Datenstände" if s["knowledge"] == "pseudo" else ""
    level_hist = histogram(s["levels"][:-1], s["value"], "Verteilung aller bisherigen Werte")
    move_hist = histogram(
        s["changes"][:-1], s["change"], "Verteilung aller bisherigen Bewegungen", zero=True
    )
    return f"""
<div class="sig" data-unit="{_e(unit if unit not in ("Saldo", "Index") else "")}">
  <div class="head"><strong>{_e(name)}</strong><span class="value">{num(s["value"], d)}<small>{_e(unit)}</small></span></div>
  <div class="part">{sparkline(hist, window)}{axis}</div>
  <div class="part">{level_hist}
    <span class="cap"><b>Niveau:</b> {_e(level_sentence(s))}</span></div>
  <div class="part">{move_hist}
    <span class="cap"><b>Bewegung:</b> {_e(move_sentence(s, cu))}{_e(six)}</span></div>
  <div class="src">{_source_line(s["sources"], by_card, period_de(s["latest_period"]))}{pseudo}</div>
</div>"""


def _trend_card(r: dict, by_card: dict[str, dict]) -> str:
    name, unit, axis, _ = STRUCTURAL_DE.get(r["key"], (r["key"], "", r["axis"], ""))
    vals = [v for _, v in r["series"]] or [0]
    note = " · EU-Wert: Mittel der Mitgliedstaaten" if "mean of member" in (r["note"] or "") else ""
    through = str(r["latest_year"]) if r["latest_year"] else "–"
    return f"""
<article class="tcard">
  <div class="top"><span class="axisname">{_e(axis)}</span><span class="val">{num(r.get("eu_value"), digits_for(vals))}<small>{_e(unit)}</small></span></div>
  <h3>{_e(name)}</h3>
  {trend_chart(r["series"], r["trend_years"])}
  <p class="lead">{_e(trend_sentence(r))}</p>
  <p>{_e(breadth_sentence(r))}</p>
  <div class="src">{_source_line(r["sources"], by_card, through)}{note}</div>
</article>"""


def _source_row(s: dict) -> str:
    link = f'<a href="{_e(s["url"])}">Dokumentation</a>' if s["url"] else ""
    return (
        f"<tr><td>{_e(s['provider'])}</td><td>{_e(s['name'])}</td>"
        f'<td class="mono">{_e(s["datasets"])}</td><td>{_e(s["licence"])}</td>'
        f'<td class="mono">{_e(s["retrieved"] or "–")}</td><td>{link}</td></tr>'
    )


def _rank_item(s: dict, share: float, sub: str) -> str:
    layer = LAYERS_DE.get(s["layer"], s["layer"])
    return (
        f'<li><div class="top"><strong>{_e(name_of(s))}</strong><span>{pct(share)}</span></div>'
        f'{rank_bar(share)}<span class="sub">{_e(layer)} · {_e(sub)}</span></li>'
    )


GUIDE_CARD = """
<article class="tcard guide">
  <span class="axisname">Lesehilfe</span>
  <h3>So lesen Sie die Karten</h3>
  <div class="fitlegend"><span><i></i>Trend der letzten fünf Jahre</span>
  <span><i class="before"></i>Trend der fünf Jahre davor</span></div>
  <p>Punkte: EU-Wert je Jahr. Liegen die beiden Linien unterschiedlich steil, hat sich der Trend
  verändert. Darunter steht, in wie vielen Mitgliedstaaten der Trend in dieselbe Richtung zeigt,
  jetzt und fünf Jahre zuvor.</p>
  <p>Jahresdaten erscheinen spät. Jede Karte nennt das letzte verfügbare Jahr.</p>
</article>"""


def render(p: dict) -> str:
    by_card = {s["card"]: s for s in p["sources"]}
    generated = datetime.fromisoformat(p["generated_utc"]).date()
    signals = p["signals"]
    moves = "".join(
        _rank_item(
            s, s["move_rank"], move_sentence(s, SIGNALS_DE.get(s["indicator"], ("", "", ""))[2])
        )
        for s in top_moves(signals)
    )
    levels = "".join(
        _rank_item(s, max(s["level_rank"], 1 - s["level_rank"]), level_sentence(s))
        for s in top_levels(signals)
    )
    cards = []
    for layer in p["layers"]:
        sigs = [s for s in signals if s["layer"] == layer]
        cards.append(
            f'<article class="layer"><h3>{_e(LAYERS_DE.get(layer, layer))}</h3>'
            + "".join(_signal_block(s, by_card) for s in sigs)
            + "</article>"
        )
    events = "".join(
        f"<li><b>{k}</b>{_e(month_de(e['month']))}: {_e(e['text'])}</li>"
        for k, e in enumerate(p["events"], start=1)
    )
    trends = "".join(_trend_card(r, by_card) for r in p["structural"])
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
  <h1>Was sich in Europa gerade bewegt</h1>
  <p class="lede">Diese Seite bewertet nicht. Sie stellt jede Zahl neben ihre eigene Geschichte:
  Wo liegt der aktuelle Wert unter allen bisherigen Werten, und wie groß ist die letzte Bewegung
  im Vergleich zu allen bisherigen Bewegungen? Es gibt keine Schwellenwerte. Was davon wichtig
  ist, entscheiden Sie.</p>
  <div class="ranks">
    <div class="panel"><h2>Die größten Bewegungen der letzten drei Monate</h2>
      <p class="hint">Prozent: Anteil aller bisherigen Bewegungen desselben Signals, die kleiner waren.</p>
      <ul class="rank">{moves}</ul></div>
    <div class="panel"><h2>Die ungewöhnlichsten Niveaus</h2>
      <p class="hint">Prozent: Anteil aller bisherigen Werte, die niedriger lagen (bei sehr niedrigen Werten: höher).</p>
      <ul class="rank">{levels}</ul></div>
  </div>
</div>

<section>
  <div class="sechead"><span class="eyebrow">Monatlich · {len(signals)} Signale auf {len(p["layers"])} Ebenen</span><h2>Jedes Signal vor seiner Geschichte</h2>
  <p><b>Kurve:</b> die letzten fünf Jahre, grau hinterlegt die letzten drei Monate.
  <b>Niveau:</b> Die Balken zeigen, wie oft das Signal seit Beginn der Reihe welchen Wert hatte;
  die blaue Linie ist der aktuelle Wert. <b>Bewegung:</b> dieselbe Darstellung für alle bisherigen
  Drei-Monats-Änderungen (beim Wachstum: Quartalsänderungen); die gestrichelte Linie ist null.
  Steht die blaue Linie am Rand der Verteilung, ist der Wert für dieses Signal selten.</p></div>
  <div class="grid">{"".join(cards)}</div>
</section>

<section class="record">
  <div class="sechead"><span class="eyebrow">Rückblick seit {p["record"]["months"][0][:4]}</span><h2>Wann sich Europa zuletzt bewegte</h2>
  <p>Jede Zeile ist eine Ebene, jede Spalte ein Monat. Die Farbe zeigt die größte Bewegung unter
  den Signalen der Ebene, gemessen an allen früheren Bewegungen desselben Signals: Je dunkler,
  desto seltener war eine so große Bewegung. Die Farbe ist stufenlos, es gibt keine Grenze. Der
  Rückblick rechnet mit dem heutigen Datenstand. Die nummerierten Dreiecke markieren Ereignisse,
  die vor der ersten Auswertung festgelegt wurden.</p></div>
  <div class="scroll">{record_svg(p["record"], p["events"])}</div>
  <div class="scale"><span>kleiner als die meisten früheren Bewegungen</span><span class="grad"></span><span>größer als fast alle</span></div>
  <ol class="events">{events}</ol>
</section>

<section>
  <div class="sechead"><span class="eyebrow">Jährlich · 27 Mitgliedstaaten</span><h2>Die langsamen Trends</h2>
  <p>Für jeden Indikator: der EU-Wert der letzten zwanzig Jahre, der Trend der letzten fünf Jahre
  neben dem der fünf Jahre davor, und in wie vielen Mitgliedstaaten der Trend in dieselbe Richtung
  zeigt.</p></div>
  <div class="trends">{trends}{GUIDE_CARD}</div>
</section>

<section>
  <div class="sechead"><span class="eyebrow">Methode</span><h2>So entsteht das Lagebild</h2></div>
  <div class="method">
    <div><h3>Nur amtliche Quellen</h3><p>Alle Zahlen stammen von EZB, Eurostat, OECD und Weltbank.
    Jede Datei wird beim Abruf unverändert archiviert. Jede Zahl auf dieser Seite lässt sich auf
    Datensatz und Abrufdatum zurückführen.</p></div>
    <div><h3>Gemessen an der eigenen Geschichte</h3><p>Prozentangaben sind Ränge: der Anteil aller
    früheren Werte oder Bewegungen desselben Signals, die kleiner waren. So werden Signale mit ganz
    unterschiedlichen Einheiten vergleichbar, ohne dass jemand eine Grenze festlegt.</p></div>
    <div><h3>Keine Prognose, kein Urteil</h3><p>Die Seite zeigt, wo sich etwas bewegt, nicht
    wohin es führt. Umfragen, Handel, Gas und Asyl haben keine historischen Datenstände; ihre
    Geschichte ist der heutige Stand der Reihe.</p></div>
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


def write(conn: psycopg.Connection, label: str | None = None) -> Path:
    payload = build_payload(conn, label)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
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
