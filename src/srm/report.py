"""Render assessment runs from the database into Markdown pages and one HTML page.

Everything on the pages is read back from stored assessments and their inputs, so the page
shows exactly what the trace in the database contains.
"""

from __future__ import annotations

import html
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from srm.snapshot import RAW_DIR

REPORTS_DIR = RAW_DIR.parents[1] / "reports" / "assessments"
DIRECTION_TEXT = {
    "strongly_increasing": "strongly increasing",
    "increasing": "increasing",
    "broadly_stable": "broadly stable",
    "decreasing": "decreasing",
    "strongly_decreasing": "strongly decreasing",
}
ARROW = {
    "strongly_increasing": "⇈",
    "increasing": "↑",
    "broadly_stable": "→",
    "decreasing": "↓",
    "strongly_decreasing": "⇊",
}


# ------------------------------------------------------------------ load
def load_run(conn: psycopg.Connection, run_id: str) -> dict:
    run = conn.execute(
        """SELECT r.run_id::text, r.as_of, r.engine_version, r.created_at, v.label, r.region_code
           FROM model.assessment_run r JOIN model.model_version v USING (model_version_id)
           WHERE r.run_id = %s""",
        (run_id,),
    ).fetchone()
    out = {
        "run_id": run[0],
        "as_of": run[1],
        "engine": run[2],
        "created_at": run[3],
        "version": run[4],
        "region": run[5],
        "regimes": [],
        "edges": [],
    }
    rows = conn.execute(
        """SELECT a.assessment_id::text, n.code, n.label, a.position, a.direction, a.velocity,
                  a.acceleration, a.data_quality, a.evidence_strength, a.model_confidence, a.summary,
                  a.would_change_view, a.details
           FROM model.assessment a JOIN model.node n USING (node_id)
           WHERE a.run_id = %s ORDER BY n.code""",
        (run_id,),
    ).fetchall()
    keys = [
        "id",
        "code",
        "label",
        "position",
        "direction",
        "velocity",
        "acceleration",
        "data_quality",
        "evidence_strength",
        "model_confidence",
        "summary",
        "would_change_view",
        "details",
    ]
    for r in rows:
        reg = dict(zip(keys, r, strict=True))
        reg["observations"] = _obs_inputs(conn, reg["id"])
        reg["claims"] = _claim_inputs(conn, reg["id"])
        out["regimes"].append(reg)
    erows = conn.execute(
        """SELECT a.assessment_id::text, e.edge_key, s.label, d.label, d.kind, a.edge_state, a.summary,
                  a.details
           FROM model.assessment a JOIN model.edge e USING (edge_id)
           JOIN model.node s ON s.node_id = e.src_node JOIN model.node d ON d.node_id = e.dst_node
           WHERE a.run_id = %s ORDER BY e.edge_key""",
        (run_id,),
    ).fetchall()
    for r in erows:
        out["edges"].append(
            dict(
                zip(
                    ["id", "key", "src", "dst", "dst_kind", "state", "summary", "details"],
                    r,
                    strict=True,
                )
            )
        )
    return out


def _obs_inputs(conn, aid):
    rows = conn.execute(
        """SELECT i.role, i.note, s.family, s.series_key, s.unit, o.period_label, o.value, o.known_from,
                  o.knowledge_precision::text, sn.path, sn.url, sn.retrieved_at, sn.sha256
           FROM model.assessment_input i
           JOIN obs.observation o ON (o.series_id, o.period, o.known_from) = (i.series_id, i.period, i.known_from)
           JOIN obs.series s ON s.series_id = o.series_id
           JOIN raw.snapshot sn ON sn.snapshot_id = o.snapshot_id
           WHERE i.assessment_id = %s ORDER BY i.note, s.series_key, o.period""",
        (aid,),
    ).fetchall()
    keys = [
        "role",
        "note",
        "family",
        "series_key",
        "unit",
        "period",
        "value",
        "known_from",
        "precision",
        "path",
        "url",
        "retrieved_at",
        "sha256",
    ]
    return [dict(zip(keys, r, strict=True)) for r in rows]


def _claim_inputs(conn, aid):
    rows = conn.execute(
        """SELECT i.role, c.claim_key, c.stance, c.statement, c.passage, c.locator, c.review_status,
                  c.reviewed_by, c.target_kind, c.target_key, d.title, d.url, d.published_at
           FROM model.assessment_input i JOIN model.evidence_claim c USING (claim_id)
           JOIN model.document d USING (document_id)
           WHERE i.assessment_id = %s ORDER BY d.published_at DESC, c.claim_key""",
        (aid,),
    ).fetchall()
    keys = [
        "role",
        "key",
        "stance",
        "statement",
        "passage",
        "locator",
        "review_status",
        "reviewed_by",
        "target_kind",
        "target_key",
        "doc_title",
        "url",
        "published_at",
    ]
    return [dict(zip(keys, r, strict=True)) for r in rows]


def _cutoff(run) -> str:
    return f"{run['as_of']:%Y-%m-%d}"


def _fmt(v, digits=2):
    return "n/a" if v is None else f"{v:.{digits}f}"


# ------------------------------------------------------------------ markdown
def render_markdown(run: dict) -> str:
    lines = [
        f"# Euro area regime assessment as of {_cutoff(run)}",
        "",
        (
            f"Model version `{run['version']}`, assessment rules `{run['engine']}`, run `{run['run_id']}`, "
            f"generated {run['created_at']:%Y-%m-%d %H:%M} UTC."
        ),
        "",
        (
            "Only data knowable at the cutoff is used. Proposed (unreviewed) evidence claims are shown "
            "but do not count toward evidence strength."
        ),
        "",
        "## Regime tendency",
        "",
        "| Regime | Position | Six-month direction | Data quality | Evidence strength | Model confidence |",
        "|---|---|---|---|---|---|",
    ]
    for r in run["regimes"]:
        lines.append(
            f"| {r['label']} | {r['position']} | {DIRECTION_TEXT[r['direction']]} | {r['data_quality']} | "
            f"{r['evidence_strength']} | {r['model_confidence']} |"
        )
    lines += [
        "",
        "## Active dynamics",
        "",
        "| Relationship | Source indicator, 12-month change | State | Higher for longer | Recession / disinflation |",
        "|---|---|---|---|---|",
    ]
    for e in run["edges"]:
        d = e["details"]
        imp = d.get("implications", {})
        lines.append(
            f"| {e['src']} → {e['dst']} | {d.get('indicator') or 'n/a'} {_fmt(d.get('change_12m'))} | "
            f"{e['state']} | {_sign(imp.get('higher_for_longer'))} | {_sign(imp.get('recession_disinflation'))} |"
        )
    for r in run["regimes"]:
        lines += [
            "",
            f"## {r['label']}",
            "",
            r["summary"],
            "",
            "### Conditions",
            "",
            "| Condition | Role | Indicator | Value | Test | Met | Latest period |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in r["details"]["conditions"]:
            met = {True: "yes", False: "no", None: "not evaluable"}[c["met"]]
            lines.append(
                f"| {c['rationale']} | {c['role']} | {c['indicator']} {c['metric']} | {_fmt(c['value'])} | "
                f"{c['comparator']} {c['threshold']:g} | {met} | {c['latest_period'] or 'n/a'} |"
            )
        lines += ["", "### Evidence known at the cutoff", ""]
        if not r["claims"]:
            lines.append("No evidence claims were published before this cutoff.")
        for cl in r["claims"]:
            lines += [
                (
                    f"- **{cl['stance']}** ({cl['review_status']}), {cl['doc_title']}, "
                    f"{cl['published_at']:%Y-%m-%d}: {cl['statement']}"
                ),
                f"  > {cl['passage']}",
            ]
        lines += ["", "### What would change the view", ""]
        lines += [f"- {p}" for p in (r["would_change_view"] or "").split("; ") if p]
        lines += ["", "### Trace to source files", ""]
        for note, obs in _group(r["observations"]).items():
            lines += [
                f"**{note}**",
                "",
                "| Series | Period | Value | Known from | Snapshot | SHA-256 |",
                "|---|---|---|---|---|---|",
            ]
            for o in obs:
                lines.append(
                    f"| {o['family']} {o['series_key']} | {o['period']} | {o['value']} | "
                    f"{o['known_from']:%Y-%m-%d %H:%M} | `{o['path']}` | `{o['sha256'][:12]}` |"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def _sign(v):
    return {1: "pushes up", -1: "pushes down"}.get(v, "none")


def _group(obs):
    g = defaultdict(list)
    for o in obs:
        g[o["note"]].append(o)
    return dict(g)


# ------------------------------------------------------------------ html
CSS = """
/* Audit dossier: cross-date regime path first, then one sheet per knowledge cutoff, read from verdict down to source file. */
:root{
  --paper:#f4f6f9; --surface:#ffffff; --ink:#18202c; --muted:#5b6575; --rule:#d8dde6;
  --accent:#1f5fa8; --hfl:#a2560f; --rd:#4b57b5; --pos:#2c7a57; --neg:#b03636; --chip:#e9edf3;
  --display:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;
  --body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#0f141b; --surface:#161d27; --ink:#e5e9ef; --muted:#9aa4b3; --rule:#2a3341;
  --accent:#86b4f0; --hfl:#e49a58; --rd:#a0a8f2; --pos:#6cc49a; --neg:#f08a8a; --chip:#222b38; color-scheme:dark}}
:root[data-theme="dark"]{
  --paper:#0f141b; --surface:#161d27; --ink:#e5e9ef; --muted:#9aa4b3; --rule:#2a3341;
  --accent:#86b4f0; --hfl:#e49a58; --rd:#a0a8f2; --pos:#6cc49a; --neg:#f08a8a; --chip:#222b38; color-scheme:dark}
[hidden]{display:none!important}
body{background:var(--paper);color:var(--ink);font:15px/1.55 var(--body)}
.wrap{max-width:1120px;margin:0 auto;padding-inline:20px;padding-block:28px 64px;display:grid;grid-template-columns:minmax(0,1fr);gap:36px}
h1,h2,h3{font-family:var(--display);text-wrap:balance;margin:0;line-height:1.15}
h1{font-size:2.1rem;font-weight:600;letter-spacing:-.01em}
h2{font-size:1.35rem;font-weight:600}
h3{font-size:1.05rem;font-weight:600}
p{margin:0;max-width:68ch}
a{color:var(--accent)}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.eyebrow{font:500 .72rem/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.mono{font-family:var(--mono);font-size:.82rem}
.muted{color:var(--muted)}
header{display:grid;gap:10px}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;font:400 .8rem/1.4 var(--mono);color:var(--muted)}
.note{border-left:3px solid var(--rule);padding-left:12px;color:var(--muted);max-width:80ch}
section{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;min-width:0}
.scroll{overflow-x:auto;min-width:0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font:500 .72rem/1.3 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);white-space:nowrap}
td.num{text-align:right;font-family:var(--mono);font-size:.86rem}
.key{display:inline-block;width:.7em;height:.7em;border-radius:2px;margin-right:6px;vertical-align:baseline}
.k-hfl{background:var(--hfl)} .k-rd{background:var(--rd)}
.chip{display:inline-block;font:500 .74rem/1.2 var(--mono);padding:3px 7px;border-radius:4px;background:var(--chip);color:var(--ink);white-space:nowrap}
.chip.yes{color:var(--pos)} .chip.no{color:var(--muted)} .chip.na{color:var(--neg)}
.chip.supporting,.chip.supports{color:var(--pos)} .chip.opposing,.chip.contradicts{color:var(--neg)} .chip.qualifies{color:var(--muted)}
.chip.strengthening{font-weight:600;color:var(--ink)} .chip.active{color:var(--ink)} .chip.weakening,.chip.conditional,.chip.unsupported{color:var(--muted)}
.bar{position:relative;height:12px;width:100%;min-width:120px;background:var(--chip);border-radius:2px}
.bar .zero{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--muted)}
.bar .fill{position:absolute;top:0;bottom:0;border-radius:2px}
.path td{white-space:nowrap}
.path .pos{font:500 .86rem/1.2 var(--body)}
.tabs{display:flex;flex-wrap:wrap;gap:6px;border-bottom:1px solid var(--rule)}
.tabs button{font:500 .85rem/1 var(--mono);color:var(--muted);background:none;border:0;border-bottom:2px solid transparent;padding:10px 10px 9px;cursor:pointer}
.tabs button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
.panel{display:grid;gap:32px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:18px;display:grid;gap:12px;min-width:0}
.card .verdict{font:600 1.6rem/1.1 var(--display)}
.card .dir{font:500 .95rem/1.3 var(--body);color:var(--muted)}
.grades{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.grades div{display:grid;gap:3px}
.grades span:first-child{font:500 .66rem/1.2 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.grades span:last-child{font:600 .95rem/1.2 var(--body)}
.regime{display:grid;gap:18px;border-top:1px solid var(--rule);padding-top:22px}
.claims{display:grid;gap:12px;list-style:none;padding:0;margin:0}
.claims li{display:grid;gap:6px;padding:12px 14px;background:var(--surface);border:1px solid var(--rule);border-radius:6px;min-width:0}
.claims blockquote{margin:0;padding-left:10px;border-left:2px solid var(--rule);color:var(--muted);font-size:.92rem}
.claims .src{font-size:.82rem;color:var(--muted)}
.change{margin:0;padding-left:18px;display:grid;gap:4px;font-size:.92rem}
details{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:10px 14px;min-width:0}
details summary{cursor:pointer;font:500 .9rem/1.4 var(--body)}
details[open] summary{margin-bottom:10px}
.trace-group{display:grid;gap:6px;margin-bottom:16px}
.trace-group h4{margin:0;font:500 .78rem/1.3 var(--mono);color:var(--muted)}
.trace td{font-size:.8rem}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:.82rem;color:var(--muted)}
.now{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
.status{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px}
.status .big{font:600 1.7rem/1.1 var(--display)}
.lv0{color:var(--muted)} .lv1{color:var(--ink)} .lv2{color:var(--accent)}
.badge{font:500 .74rem/1.2 var(--mono);padding:3px 8px;border-radius:4px;border:1px solid var(--accent);color:var(--accent)}
.layers{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:12px}
.layer{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:12px 14px;display:grid;align-content:start;gap:10px;min-width:0}
.layer.on{border-color:var(--accent)}
.layer h4{margin:0;font:600 .95rem/1.2 var(--body);display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.sig{display:grid;gap:2px;font-size:.86rem}
.sig .name{min-width:0}
.sig .val{font-family:var(--mono);font-size:.78rem;color:var(--ink)}
.sig .why{font-size:.76rem;color:var(--muted)}
.flag{font:500 .7rem/1.2 var(--mono);padding:2px 6px;border-radius:3px;background:var(--chip)}
.flag.speed,.flag.turn{color:var(--accent)}
.timeline svg{width:100%;height:auto;display:block}
.timeline text{fill:var(--muted);font:10px var(--mono)}
.lg{display:inline-block;width:.9em;height:.9em;border-radius:2px;vertical-align:-1px;margin-right:5px}
.struct td.flags{font-family:var(--mono);font-size:.74rem;white-space:nowrap;letter-spacing:.5px}
@media (max-width:560px){h1{font-size:1.6rem}.grades{grid-template-columns:1fr 1fr}}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""

JS = """
(function(){
  var tabs=[].slice.call(document.querySelectorAll('.tabs button'));
  function show(id){
    tabs.forEach(function(b){var on=b.dataset.panel===id;b.setAttribute('aria-selected',on?'true':'false');
      document.getElementById(b.dataset.panel).hidden=!on;});
  }
  tabs.forEach(function(b){b.addEventListener('click',function(){show(b.dataset.panel);
    try{history.replaceState(null,'','#'+b.dataset.panel)}catch(e){}});});
  var h=(location.hash||'').slice(1);
  if(h&&document.getElementById(h)){show(h)}
})();
"""


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _bar(net: float, color: str) -> str:
    left = 50 if net >= 0 else 50 + net * 50
    width = abs(net) * 50
    return (
        f'<div class="bar" role="img" aria-label="net score {net:+.2f} on a scale from -1 to +1">'
        f'<div class="zero"></div><div class="fill" style="left:{left:.1f}%;width:{width:.1f}%;'
        f'background:var(--{color})"></div></div>'
    )


def _regime_color(code: str) -> str:
    return "hfl" if code == "higher_for_longer" else "rd"


def _met_chip(met):
    return {
        True: '<span class="chip yes">met</span>',
        False: '<span class="chip no">not met</span>',
        None: '<span class="chip na">not evaluable</span>',
    }[met]


def _effect(v):
    return {1: "↑ pushes toward", -1: "↓ pushes away"}.get(v, "–")


LEVEL_TEXT = {0: "Quiet", 1: "One layer is moving", 2: "Something is happening"}
LEVEL_FILL = {
    0: "var(--chip)",
    1: "color-mix(in srgb, var(--accent) 45%, var(--chip))",
    2: "var(--accent)",
}


def _signal_rows(sigs: list[dict], labels: dict[str, str]) -> str:
    rows = []
    for g in sigs:
        name = labels.get(g["indicator"], g["indicator"])
        flags = []
        if g.get("unusual"):
            flags.append('<span class="flag speed">unusual speed</span>')
        if g.get("turn"):
            flags.append('<span class="flag turn">direction change</span>')
        if g.get("unusual") is None:
            flags.append('<span class="flag">not evaluable</span>')
        chg = "" if g.get("change") is None else f"3-mo change {g['change']:+.2f}"
        why = ""
        if g.get("threshold") is not None:
            why = f"usual 3-month moves stay within ±{g['threshold']:.2f}"
        if g.get("note"):
            why = g["note"]
        if g.get("knowledge") == "pseudo":
            why += " · no data vintages (approximation in tests)"
        rows.append(
            f'<div class="sig"><span class="name">{_e(name)} {" ".join(flags)}</span>'
            f'<span class="val">{_e(g.get("latest_period") or "")} {_e(chg)}</span>'
            f'<span class="why">{_e(why)}</span></div>'
        )
    return "\n".join(rows)


def _timeline_svg(timeline: list[dict], events: list[dict]) -> str:
    n = len(timeline)
    cw, ch, left, top = 4, 22, 4, 6
    width = left * 2 + n * cw
    height = top + ch + 34
    idx = {t["month"]: i for i, t in enumerate(timeline)}
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Detector level by month">'
    ]
    for i, t in enumerate(timeline):
        x = left + i * cw
        parts.append(
            f'<rect x="{x}" y="{top}" width="{cw - 1}" height="{ch}" fill="{LEVEL_FILL[t["level"]]}">'
            f"<title>{t['month']}: {LEVEL_TEXT[t['level']]}{' (new alarm)' if t['onset'] else ''}"
            f"{': ' + ', '.join(t['layers']) if t['layers'] else ''}</title></rect>"
        )
        if t["onset"]:
            parts.append(
                f'<rect x="{x}" y="{top - 5}" width="{cw - 1}" height="3" fill="var(--ink)"/>'
            )
        if t["month"].endswith("-01") and int(t["month"][:4]) % 2 == 0:
            parts.append(
                f'<line x1="{x}" x2="{x}" y1="{top + ch}" y2="{top + ch + 4}" stroke="var(--muted)" stroke-width="1"/>'
                f'<text x="{x}" y="{top + ch + 14}">{t["month"][:4]}</text>'
            )
    for ev in events:
        if ev["month"] in idx:
            x = left + idx[ev["month"]] * cw + cw / 2
            y = top + ch + 20
            mark = {
                "new alarm": "var(--accent)",
                "alarm already running": "var(--muted)",
                "missed": "var(--neg)",
            }[ev["status"]]
            parts.append(
                f'<path d="M{x - 4},{y + 8} L{x},{y} L{x + 4},{y + 8} Z" fill="{mark}">'
                f"<title>{_e(ev['month'])} {_e(ev['event'])}: {_e(ev['status'])}</title></path>"
            )
    parts.append("</svg>")
    return "".join(parts)


def render_happening(p: dict) -> str:
    labels = p.get("indicator_labels", {})
    now = p["now"]
    by_layer: dict[str, list[dict]] = {}
    for g in now["signals"]:
        by_layer.setdefault(g["layer"], []).append(g)
    lvl = now["level"]
    out = [
        '<section class="now" id="now">',
        "<h2>What is happening now</h2>",
        f'<div class="status"><span class="big lv{lvl}">{LEVEL_TEXT[lvl]}</span>'
        + ('<span class="badge">new alarm</span>' if now["onset"] else "")
        + f'<span class="muted mono">as of {_e(now["month"])} · model {_e(p["model_version"])}</span></div>',
        (
            '<p class="muted">Each signal is compared with its own history: a 3-month move larger than 95% of its past '
            "moves is unusual speed; a 6-month move against a consistent earlier run is a direction change. "
            "When at least two layers move, something is happening. No fixed levels are used.</p>"
        ),
        '<div class="layers">',
    ]
    for layer in p["layers"]:
        sigs = by_layer.get(layer["key"], [])
        on = layer["key"] in now["active_layers"]
        state = "moving" if on else "quiet"
        out.append(
            f'<article class="layer{" on" if on else ""}"><h4><span>{_e(layer["label"])}</span>'
            f'<span class="flag{" speed" if on else ""}">{state}</span></h4>{_signal_rows(sigs, labels)}</article>'
        )
    out.append("</div>")
    ts = p.get("test_summary", {})
    out += [
        '<div class="timeline"><h3>Detector history, monthly since 2008</h3>',
        (
            '<div class="legend"><span><span class="lg" style="background:var(--chip)"></span>quiet</span>'
            f'<span><span class="lg" style="background:{LEVEL_FILL[1]}"></span>one layer moving</span>'
            '<span><span class="lg" style="background:var(--accent)"></span>something is happening</span>'
            '<span><span class="lg" style="background:var(--ink);height:.3em"></span>new alarm</span>'
            '<span>▲ reference event: <span style="color:var(--accent)">new alarm</span>, '
            '<span class="muted">alarm already running</span>, <span style="color:var(--neg)">missed</span></span></div>'
        ),
        f'<div class="scroll">{_timeline_svg(p["timeline"], p["events"])}</div>',
    ]
    if ts:
        out.append(
            '<div class="scroll"><table><thead><tr><th>Version</th><th>New alarm at event</th><th>Already running</th>'
            "<th>Missed</th><th>New alarms outside events</th></tr></thead><tbody>"
        )
        for lab, sc in ts.items():
            st = [e["status"] for e in sc["events"]]
            out.append(
                f'<tr><td class="mono">{_e(lab)}</td><td class="num">{st.count("new alarm")}</td>'
                f'<td class="num">{st.count("alarm already running")}</td><td class="num">{st.count("missed")}</td>'
                f'<td class="num">{len(sc["false_alarms"])}</td></tr>'
            )
        out.append("</tbody></table></div>")
    years: dict[str, list[str]] = {}
    for t in p["timeline"]:
        years.setdefault(t["month"][:4], []).append("N" if t["onset"] else str(t["level"]))
    out.append(
        "<details><summary>Levels as a table (N = new alarm, 2 = alarm, 1 = one layer, 0 = quiet)</summary>"
        '<div class="scroll"><table><tbody>'
        + "".join(
            f'<tr><td class="mono">{y}</td><td class="mono">{" ".join(v)}</td></tr>'
            for y, v in years.items()
        )
        + "</tbody></table></div></details></div>"
    )
    # yearly structural layer
    hist = p.get("structural_history", {})
    yrs = sorted(hist)[-12:]
    out += [
        "<h3>Structural axes, yearly</h3>",
        (
            '<p class="muted">Five-year trend against the previous five years, for the EU and each member state. A '
            "Europe-wide movement is flagged when unusually many member states change trend in the same direction. "
            f"History columns {yrs[0] if yrs else ''}–{yrs[-1] if yrs else ''}: E = Europe-wide movement, "
            "D = EU trend changed direction, · = nothing unusual, – = not assessable.</p>"
        ),
        (
            '<div class="scroll"><table class="struct"><thead><tr><th>Axis</th><th>Indicator</th><th>Latest</th>'
            "<th>EU value</th><th>Trend per year (before → now)</th><th>Now</th><th>History</th></tr></thead><tbody>"
        ),
    ]
    for s_ in p.get("structural_now", []):
        now_flags = []
        if s_.get("unusual"):
            now_flags.append(
                f'<span class="flag speed">Europe-wide, toward {_e(s_["toward"])}</span>'
            )
        if s_.get("turn"):
            now_flags.append('<span class="flag turn">direction change</span>')
        if s_.get("breadth") is not None:
            now_flags.append(
                f'<span class="muted">{round(100 * s_["breadth"])}% of states'
                + (
                    f" (usual up to {round(100 * s_['breadth_threshold'])}%)"
                    if s_.get("breadth_threshold") is not None
                    else ""
                )
                + "</span>"
            )
        trend = (
            ""
            if s_.get("trend_now") is None
            else f"{s_['trend_before']:+.2f} → {s_['trend_now']:+.2f}"
        )
        flags = []
        for y in yrs:
            r = next((x for x in hist[y] if x["key"] == s_["key"]), None)
            if r is None or r["unusual"] is None:
                flags.append("–")
            else:
                flags.append(("E" if r["unusual"] else "") + ("D" if r["turn"] else "") or "·")
        out.append(
            f"<tr><td>{_e(s_['axis'].replace('_', ' '))}</td><td>{_e(s_['label'])}</td>"
            f'<td class="mono">{_e(s_.get("latest_year") or "")}</td>'
            f'<td class="num">{"" if s_.get("eu_value") is None else _e(s_["eu_value"])}</td>'
            f'<td class="mono">{_e(trend)}</td><td>{" ".join(now_flags)}</td>'
            f'<td class="flags">{" ".join(flags)}</td></tr>'
        )
    out.append("</tbody></table></div></section>")
    return "\n".join(out)


def render_html(runs: list[dict], happening: dict | None = None) -> str:
    runs = sorted(runs, key=lambda r: r["as_of"])
    latest = runs[-1]
    version = latest["version"]
    gen = datetime.now(UTC)
    parts = [
        "<title>Euro Area Regime Monitor</title>",
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        (
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500'
            '&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">'
        ),
        f"<style>{CSS}</style>",
        '<div class="wrap">',
        "<header>",
        '<div class="eyebrow">Strategic Regime Monitor · Euro area</div>',
        "<h1>Euro Area Regime Monitor</h1>",
        (
            f'<div class="meta"><span>model {_e(version)}</span><span>rules {_e(latest["engine"])}</span>'
            f"<span>generated {gen:%Y-%m-%d %H:%M} UTC</span><span>{len(runs)} knowledge cutoffs</span></div>"
        ),
        (
            '<p class="note">Each cutoff uses only data that was knowable at that moment: ECB Real-Time Database '
            "vintages, Eurostat revision dates, OECD editions, and today's downloads only for today. Evidence claims "
            "marked proposed are unreviewed: they are shown here but do not count toward evidence strength.</p>"
        ),
        "</header>",
        render_happening(happening) if happening else "",
        "<section>",
        "<h2>Regime path</h2>",
        (
            '<div class="legend"><span><span class="key k-hfl"></span>Higher for longer</span>'
            '<span><span class="key k-rd"></span>Recession / disinflation</span>'
            "<span>Bar: net score from -1 (opposing conditions dominate) to +1 (all supporting met), zero in the middle.</span></div>"
        ),
        (
            '<div class="scroll"><table class="path"><thead><tr><th>Cutoff</th><th>Higher for longer</th><th></th>'
            "<th>Recession / disinflation</th><th></th></tr></thead><tbody>"
        ),
    ]
    for run in runs:
        regs = {r["code"]: r for r in run["regimes"]}
        row = f'<tr><td class="mono"><a href="#{_panel_id(run)}">{_cutoff(run)}</a></td>'
        for code in ("higher_for_longer", "recession_disinflation"):
            r = regs[code]
            row += (
                f'<td style="width:22%">{_bar(r["details"]["net"], _regime_color(code))}</td>'
                f'<td><span class="pos">{_e(r["position"])}</span> '
                f'<span class="muted">{ARROW[r["direction"]]} {_e(DIRECTION_TEXT[r["direction"]])}</span></td>'
            )
        parts.append(row + "</tr>")
    parts += [
        "</tbody></table></div>",
        "</section>",
        "<section>",
        "<h2>Assessment by cutoff</h2>",
        '<div class="tabs" role="tablist">',
    ]
    for run in runs:
        sel = "true" if run is latest else "false"
        parts.append(
            f'<button type="button" role="tab" id="tab-{_panel_id(run)}" data-panel="{_panel_id(run)}" '
            f'aria-selected="{sel}">{_cutoff(run)}</button>'
        )
    parts.append("</div>")
    for run in runs:
        parts.append(_panel(run, hidden=run is not latest))
    parts += [
        "</section>",
        (
            '<footer class="muted mono" style="font-size:.78rem">Built from the strategic-pulse repository: '
            "source cards in sources/, raw snapshots and documents in data/raw/, model versions in model/versions/.</footer>"
        ),
        "</div>",
        f"<script>{JS}</script>",
    ]
    return "\n".join(parts) + "\n"


def _panel_id(run) -> str:
    return "d" + _cutoff(run)


def _panel(run: dict, hidden: bool) -> str:
    p = [
        f'<div class="panel" id="{_panel_id(run)}" role="tabpanel"{" hidden" if hidden else ""}>',
        (
            f'<div class="meta"><span>as of {run["as_of"]:%Y-%m-%d %H:%M} UTC</span><span>run {_e(run["run_id"][:8])}</span>'
            f"<span>model {_e(run['version'])}</span></div>"
        ),
        '<div class="cards">',
    ]
    for r in run["regimes"]:
        color = _regime_color(r["code"])
        p.append(
            f'<article class="card"><div class="eyebrow"><span class="key k-{color}"></span>{_e(r["label"])}</div>'
            f'<div class="verdict">{_e(r["position"])}</div>'
            f'<div class="dir">{ARROW[r["direction"]]} {_e(DIRECTION_TEXT[r["direction"]])} over six months · '
            f"net {r['details']['net']:+.2f} (was {r['details']['net_6m_ago']:+.2f})</div>"
            f"{_bar(r['details']['net'], color)}"
            f'<div class="grades"><div><span>Data quality</span><span>{_e(r["data_quality"])}</span></div>'
            f"<div><span>Evidence strength</span><span>{_e(r['evidence_strength'])}</span></div>"
            f"<div><span>Model confidence</span><span>{_e(r['model_confidence'])}</span></div></div>"
            f"<p>{_e(r['summary'])}</p></article>"
        )
    p.append("</div>")
    p += [
        "<section><h3>Active dynamics</h3>",
        (
            '<p class="muted">A relationship is active when its source indicator moved more than 0.25 points over 12 months. '
            "Its effect on each regime follows the signs along the path through the relationship graph.</p>"
        ),
        (
            '<div class="scroll"><table><thead><tr><th>Relationship</th><th>Source indicator</th><th>12-month change</th>'
            "<th>State</th><th>Higher for longer</th><th>Recession / disinflation</th></tr></thead><tbody>"
        ),
    ]
    for e in run["edges"]:
        d = e["details"]
        imp = d.get("implications", {})
        p.append(
            f'<tr><td>{_e(e["src"])} → {_e(e["dst"])}</td><td class="mono">{_e(d.get("indicator") or "n/a")}</td>'
            f'<td class="num">{_fmt(d.get("change_12m"))}</td><td><span class="chip {e["state"]}">{_e(e["state"])}</span></td>'
            f"<td>{_effect(imp.get('higher_for_longer'))}</td><td>{_effect(imp.get('recession_disinflation'))}</td></tr>"
        )
    p.append("</tbody></table></div></section>")
    for r in run["regimes"]:
        p.append(_regime_section(r))
    p.append("</div>")
    return "\n".join(p)


def _regime_section(r: dict) -> str:
    color = _regime_color(r["code"])
    s = [
        f'<div class="regime"><h3><span class="key k-{color}"></span>{_e(r["label"])}</h3>',
        (
            '<div class="scroll"><table><thead><tr><th>Condition</th><th>Role</th><th>Indicator</th><th>Value</th>'
            "<th>Test</th><th>Result</th><th>Latest period</th></tr></thead><tbody>"
        ),
    ]
    for c in r["details"]["conditions"]:
        months = c.get("age_months")
        age = "" if months is None else " (current)" if months == 0 else f" ({months} mo old)"
        s.append(
            f'<tr><td>{_e(c["rationale"])}</td><td><span class="chip {c["role"]}">{_e(c["role"])}</span></td>'
            f'<td class="mono">{_e(c["indicator"])} · {_e(c["metric"])}</td><td class="num">{_fmt(c["value"])}</td>'
            f'<td class="mono">{_e(c["comparator"])} {c["threshold"]:g}</td><td>{_met_chip(c["met"])}</td>'
            f'<td class="mono">{_e(c["latest_period"] or "n/a")}{_e(age)}</td></tr>'
        )
    s.append("</tbody></table></div>")
    s.append("<h3>Evidence known at the cutoff</h3>")
    if r["claims"]:
        s.append('<ul class="claims">')
        for cl in r["claims"]:
            target = cl["target_key"].replace("_", " ")
            s.append(
                f'<li><div><span class="chip {cl["stance"]}">{_e(cl["stance"])}</span> '
                f'<span class="chip">{_e(cl["review_status"])}</span> <span class="muted">on {_e(target)}</span></div>'
                f"<div>{_e(cl['statement'])}</div><blockquote>{_e(cl['passage'])}</blockquote>"
                f'<div class="src"><a href="{_e(cl["url"])}">{_e(cl["doc_title"])}</a> · published '
                f"{cl['published_at']:%Y-%m-%d} · {_e(cl['locator'])}</div></li>"
            )
        s.append("</ul>")
    else:
        s.append('<p class="muted">No cited document had been published before this cutoff.</p>')
    s.append('<h3>What would change the view</h3><ul class="change">')
    s += [f'<li class="mono">{_e(x)}</li>' for x in (r["would_change_view"] or "").split("; ") if x]
    s.append("</ul>")
    groups = _group(r["observations"])
    s.append(
        f"<details><summary>Trace to source files: {len(r['observations'])} observations behind "
        f"{len(groups)} conditions</summary>"
    )
    for note, obs in groups.items():
        s.append(
            f'<div class="trace-group"><h4>{_e(note)}</h4><div class="scroll"><table class="trace"><thead><tr>'
            "<th>Series</th><th>Period</th><th>Value</th><th>Known from</th><th>Snapshot file</th>"
            "<th>SHA-256</th></tr></thead><tbody>"
        )
        for o in obs:
            s.append(
                f'<tr><td class="mono">{_e(o["family"])}<br>{_e(o["series_key"])}</td><td class="mono">{_e(o["period"])}</td>'
                f'<td class="num">{_e(o["value"])}</td><td class="mono">{o["known_from"]:%Y-%m-%d %H:%M}<br>'
                f'<span class="muted">{_e(o["precision"])}</span></td>'
                f'<td class="mono"><a href="{_e(o["url"])}">{_e(o["path"])}</a></td>'
                f'<td class="mono">{_e(o["sha256"][:16])}</td></tr>'
            )
        s.append("</tbody></table></div></div>")
    s.append("</details></div>")
    return "\n".join(s)


# ------------------------------------------------------------------ write
def write_reports(conn: psycopg.Connection, run_ids: list[str]) -> list[Path]:
    import json

    runs = [load_run(conn, rid) for rid in run_ids]
    written = []
    by_version = defaultdict(list)
    for run in runs:
        by_version[run["version"]].append(run)
    for version, vruns in by_version.items():
        folder = REPORTS_DIR / version
        folder.mkdir(parents=True, exist_ok=True)
        for run in vruns:
            path = folder / f"{_cutoff(run)}.md"
            path.write_text(render_markdown(run), encoding="utf-8")
            written.append(path)
        page = folder / "index.html"
        det = REPORTS_DIR.parent / "detector" / f"{version}.json"
        happening = json.loads(det.read_text(encoding="utf-8")) if det.exists() else None
        page.write_text(render_html(vruns, happening), encoding="utf-8")
        written.append(page)
    return written
