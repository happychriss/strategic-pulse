"""Monthly pipeline: pull -> build -> tests -> assess -> pages -> run log.

    python -m srm.run_monthly            # full run
    python -m srm.run_monthly --no-pull  # rebuild and reassess from the archive only

Exit codes: 0 all good; 2 some pulls failed (everything else ran); 1 tests failed or the
pipeline broke (no pages or run log written). Git, pull requests and publishing are left to
the caller (the monthly routine), so this script never changes anything outside the repo tree.

The run log in reports/runs/ records what was pulled, the latest value of every indicator and
each regime position. Comparing it with the previous run log gives "what changed".
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime

from srm.snapshot import RAW_DIR

REPO = RAW_DIR.parents[1]
RUNS_DIR = REPO / "reports" / "runs"
PHASE1_CUTOFFS = ("2019-12-31", "2021-12-31", "2022-12-31", "2024-12-31")


def indicator_snapshot(conn, at: datetime) -> dict[str, dict]:
    from srm.indicators import current_version, indicator_series, metric

    mv = current_version(conn)
    codes = [
        r[0]
        for r in conn.execute(
            "SELECT code FROM model.indicator WHERE model_version_id = %s ORDER BY code", (mv,)
        ).fetchall()
    ]
    out = {}
    for code in codes:
        m = metric(indicator_series(conn, code, at, mv), "level")
        out[code] = {"period": m[1], "value": m[0]} if m else {"period": None, "value": None}
    return out


def diff_runs(prev: dict | None, cur: dict) -> list[str]:
    """Plain-language list of changes between two run logs."""
    if not prev:
        return ["First run log: baseline recorded, nothing to compare with."]
    changes = []
    for code, now in cur["indicators"].items():
        before = prev.get("indicators", {}).get(code)
        if not before or before == now:
            continue
        if before["period"] != now["period"]:
            changes.append(
                f"{code}: new period {now['period']} = {now['value']} (was {before['period']} = {before['value']})"
            )
        else:
            changes.append(
                f"{code}: {now['period']} revised from {before['value']} to {now['value']}"
            )
    for code, now in cur["regimes"].items():
        before = prev.get("regimes", {}).get(code)
        if before and before != now:
            changes.append(
                f"{code}: {before['position']}, {before['direction']} -> {now['position']}, {now['direction']}"
            )
    return changes or ["No change in indicators or regime positions since the previous run."]


def previous_log(today: str) -> dict | None:
    logs = sorted(p for p in RUNS_DIR.glob("*.json") if p.stem < today)
    return json.loads(logs[-1].read_text(encoding="utf-8")) if logs else None


def main(argv: list[str]) -> int:
    from srm.assess import assess, parse_as_of, persist
    from srm.build import build
    from srm.db import connect
    from srm.model_content import current_label
    from srm.pull import pull
    from srm.report import write_reports

    started = datetime.now(UTC)
    today = started.strftime("%Y-%m-%d")
    pulls = [] if "--no-pull" in argv else pull(verbose=True)
    failed = [p for p in pulls if p["status"] == "failed"]

    with connect() as conn:
        conn.autocommit = True
        build_report = build(conn, verbose=True)
        tests = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        if tests.returncode != 0:
            print(tests.stdout[-4000:], tests.stderr[-2000:])
            print("TESTS FAILED: no pages or run log written")
            return 1
        cutoffs = [parse_as_of(d) for d in PHASE1_CUTOFFS] + [started]
        runs, regimes = [], {}
        for at in cutoffs:
            report = assess(conn, at)
            runs.append(persist(conn, report))
        for r in report["regimes"]:  # the last cutoff is now
            regimes[r.code] = {
                "position": r.position,
                "direction": r.direction,
                "net": r.net,
                "data_quality": r.data_quality,
                "evidence_strength": r.evidence_strength,
                "model_confidence": r.model_confidence,
            }
        from srm.detect import detect
        from srm.detect import run as run_detector

        run_detector(conn)  # historical test + page data for the "what is happening" view
        pages = write_reports(conn, runs)
        detection = detect(conn, started)
        log = {
            "date": today,
            "started_utc": started.isoformat(),
            "model_version": current_label(),
            "pulls": pulls,
            "build": build_report,
            "tests": tests.stdout.strip().splitlines()[-1] if tests.stdout.strip() else "",
            "indicators": indicator_snapshot(conn, started),
            "regimes": regimes,
            "pages": [str(p.relative_to(REPO)) for p in pages],
            "detector": {
                "level": detection.level,
                "unusual_layers": detection.unusual_layers,
                "unusual_signals": [
                    {
                        "layer": x.layer,
                        "indicator": x.indicator,
                        "period": x.latest_period,
                        "change_3m": x.change,
                        "threshold": x.threshold,
                    }
                    for x in detection.signals
                    if x.unusual
                ],
                "not_evaluable": [x.indicator for x in detection.signals if x.unusual is None],
            },
        }
    log["changes"] = diff_runs(previous_log(today), log)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{today}.json").write_text(
        json.dumps(log, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (RUNS_DIR / f"{today}.md").write_text(render_log(log), encoding="utf-8")
    print(render_log(log))
    return 2 if failed else 0


def render_log(log: dict) -> str:
    pulls = log["pulls"]
    lines = [
        f"# Monthly run {log['date']}",
        "",
        f"Model version `{log['model_version']}`. Tests: {log['tests'] or 'not run'}.",
        "",
        "## Is something happening?",
        "",
        *_detector_lines(log.get("detector")),
        "",
        "## What changed",
        "",
        *[f"- {c}" for c in log["changes"]],
        "",
        "## Regimes now",
        "",
        "| Regime | Position | Six-month direction | Data quality | Evidence strength | Model confidence |",
        "|---|---|---|---|---|---|",
        *[
            f"| {k} | {v['position']} | {v['direction']} | {v['data_quality']} | {v['evidence_strength']} | "
            f"{v['model_confidence']} |"
            for k, v in log["regimes"].items()
        ],
        "",
        "## Indicators now",
        "",
        "| Indicator | Latest period | Value |",
        "|---|---|---|",
        *[f"| {k} | {v['period']} | {v['value']} |" for k, v in log["indicators"].items()],
        "",
        "## Pulls",
        "",
        (
            f"{sum(p['status'] == 'new' for p in pulls)} new, {sum(p['status'] == 'unchanged' for p in pulls)} "
            f"unchanged, {sum(p['status'] == 'failed' for p in pulls)} failed."
        ),
        "",
        *[
            f"- FAILED {p['card']}/{p['label']}: {p.get('error', '')[:200]}"
            for p in pulls
            if p["status"] == "failed"
        ],
    ]
    return "\n".join(lines) + "\n"


def _detector_lines(d: dict | None) -> list[str]:
    if not d:
        return ["Detector not run."]
    text = {
        0: "Quiet: no unusual moves in any layer.",
        1: "Unusual move in one layer.",
        2: "Something is happening: unusual moves in several layers.",
    }[d["level"]]
    lines = [f"Level {d['level']}. {text}"]
    lines += [
        f"- {u['layer']}: {u['indicator']} {u['period']}, 3-month change {u['change_3m']} "
        f"(usual range up to {u['threshold']})"
        for u in d["unusual_signals"]
    ]
    if d["not_evaluable"]:
        lines.append(f"Not evaluable this month: {', '.join(d['not_evaluable'])}.")
    return lines


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
