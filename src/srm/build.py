"""Rebuild the database from source cards and raw snapshots.

    python -m srm.build            # migrate, sync cards, register snapshots, load observations

The build is deterministic and idempotent: running it twice changes nothing, and adding a
snapshot only appends or closes knowledge intervals. Observations an assessment refers to
cannot be deleted (foreign key RESTRICT).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from srm.db import connect, migrate
from srm.knowledge import (
    DENSE_RULES,
    PRECISION,
    Event,
    collapse,
    edition_time,
    parse_lag_days,
    release_time,
    revdate_time,
)
from srm.parsers import PARSERS, Point
from srm.periods import parse_period
from srm.snapshot import RAW_DIR
from srm.source_cards import load_cards

REPO = RAW_DIR.parents[1]
REGION_SYSTEM = {"ECB": "ECB", "ESTAT": "ESTAT", "OECD": "OECD"}


def stable_uuid(*parts: str) -> str:
    h = hashlib.md5("|".join(parts).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def dataset_for_url(url: str) -> str | None:
    if m := re.search(r"data-api\.ecb\.europa\.eu/service/data/([^/?]+)/", url):
        return f"ECB:{m.group(1)}"
    if m := re.search(r"/eurostat/api/dissemination/statistics/1\.0/data/([^/?]+)", url):
        return f"ESTAT:{m.group(1)}"
    if m := re.search(r"sdmx\.oecd\.org/public/rest/data/[^,/]+,([^,/]+),", url):
        return f"OECD:{m.group(1)}"
    return None


# ------------------------------------------------------------------ registry sync
def sync_cards(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    """Upsert cards and datasets. Returns dataset_id -> dataset config (with card_id)."""
    datasets: dict[str, dict[str, Any]] = {}
    with conn.transaction():
        for card in load_cards():
            d = card.data
            body = json.dumps(d, sort_keys=True, default=str)
            conn.execute(
                """INSERT INTO ref.source_card (card_id, provider, name, role, phase, vintage_support,
                       verification_status, superseded_by, card, card_sha256, synced_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                   ON CONFLICT (card_id) DO UPDATE SET provider=EXCLUDED.provider, name=EXCLUDED.name,
                       role=EXCLUDED.role, phase=EXCLUDED.phase, vintage_support=EXCLUDED.vintage_support,
                       verification_status=EXCLUDED.verification_status,
                       superseded_by=EXCLUDED.superseded_by, card=EXCLUDED.card,
                       card_sha256=EXCLUDED.card_sha256, synced_at=now()
                   WHERE ref.source_card.card_sha256 IS DISTINCT FROM EXCLUDED.card_sha256""",
                (
                    card.id,
                    d["provider"],
                    d["name"],
                    d["role"],
                    d["phase"],
                    d["temporal"]["vintage_support"],
                    d["verification"]["status"],
                    d.get("superseded_by"),
                    body,
                    hashlib.sha256(body.encode()).hexdigest(),
                ),
            )
            for ds in d.get("datasets") or []:
                cfg = {**ds, "card_id": card.id, "family": ds.get("family", ds["code"])}
                datasets[ds["code"]] = cfg
                conn.execute(
                    """INSERT INTO ref.dataset (dataset_id, card_id, family, parser, knowledge_rule,
                           revision_class, release_lag)
                       VALUES (%s,%s,%s,%s,%s,%s,%s::interval)
                       ON CONFLICT (dataset_id) DO UPDATE SET card_id=EXCLUDED.card_id,
                           family=EXCLUDED.family, parser=EXCLUDED.parser,
                           knowledge_rule=EXCLUDED.knowledge_rule,
                           revision_class=EXCLUDED.revision_class, release_lag=EXCLUDED.release_lag""",
                    (
                        ds["code"],
                        card.id,
                        cfg["family"],
                        ds["parser"],
                        ds["knowledge_rule"],
                        ds["revision_class"],
                        ds.get("release_lag"),
                    ),
                )
    return datasets


@dataclass
class Snap:
    snapshot_id: str
    card_id: str
    dataset_id: str | None
    path: Path
    url: str
    retrieved_at: datetime
    skip_reason: str | None


def register_snapshots(conn: psycopg.Connection, datasets: dict[str, dict[str, Any]]) -> list[Snap]:
    snaps = []
    with conn.transaction():
        for meta_path in sorted(RAW_DIR.glob("*/*.meta.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            data_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json"))
            rel = str(data_path.relative_to(REPO))
            ds = dataset_for_url(meta["url"])
            skip = None
            if ds not in datasets:
                skip, ds = f"no declared dataset for {ds}", None
            elif ds == "ECB:RTD" and "includeHistory=true" not in meta["url"]:
                skip = "RTD catalog without vintage history"
            snap = Snap(
                snapshot_id=stable_uuid(rel),
                card_id=meta["card_id"],
                dataset_id=ds,
                path=data_path,
                url=meta["url"],
                retrieved_at=datetime.fromisoformat(meta["retrieved_at_utc"]),
                skip_reason=skip,
            )
            snaps.append(snap)
            conn.execute(
                """INSERT INTO raw.snapshot (snapshot_id, card_id, dataset_id, label, path, url,
                       retrieved_at, sha256, bytes, compression, load_status, load_note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (snapshot_id) DO UPDATE SET dataset_id=EXCLUDED.dataset_id,
                       load_status=CASE WHEN EXCLUDED.load_status='skipped' THEN 'skipped'
                                        ELSE raw.snapshot.load_status END,
                       load_note=EXCLUDED.load_note""",
                (
                    snap.snapshot_id,
                    snap.card_id,
                    ds,
                    meta["label"],
                    rel,
                    meta["url"],
                    snap.retrieved_at,
                    meta["sha256"],
                    meta["bytes"],
                    meta.get("stored_compression"),
                    "skipped" if skip else "pending",
                    skip,
                ),
            )
    return snaps


# ------------------------------------------------------------------ observations
def _event_time(rule: str, p: Point, snap: Snap) -> datetime | None:
    if rule == "source_vintage_log":
        return datetime.fromisoformat(p.vintage) if p.vintage else None
    if rule == "revdate_dimension":
        return revdate_time(p.vintage)
    if rule == "edition_dimension":
        return edition_time(p.vintage)
    return snap.retrieved_at  # ingestion; release_rule adjusted later


def build_family(
    conn: psycopg.Connection,
    family: str,
    snaps: list[Snap],
    datasets: dict[str, dict[str, Any]],
    aliases: dict[tuple[str, str], str],
) -> dict[str, int]:
    rules = {datasets[s.dataset_id]["knowledge_rule"] for s in snaps}
    if len(rules) != 1:
        raise RuntimeError(f"family {family} mixes knowledge rules {rules}")
    rule = rules.pop()
    system = REGION_SYSTEM[family.split(":")[0]]
    series_meta: dict[str, Point] = {}
    events: dict[tuple[str, str], list[Event]] = defaultdict(list)
    vintages: dict[str, set[datetime]] = defaultdict(set)
    first_seen: dict[tuple[str, str], tuple[datetime, Any]] = {}
    lag = {s.dataset_id: datasets[s.dataset_id].get("release_lag") for s in snaps}

    for snap in sorted(snaps, key=lambda s: s.retrieved_at):
        parser = PARSERS[datasets[snap.dataset_id]["parser"]]
        for p in parser(snap.path):
            series_meta.setdefault(p.series_key, p)
            t = _event_time(rule, p, snap)
            if t is None:
                continue
            key = (p.series_key, p.period_label)
            attrs = tuple(sorted(p.attrs.items())) if p.attrs else None
            if rule == "release_rule":
                # First sighting: known at release time. A later different value means the
                # "unrevised" assumption broke; date that correction by retrieval time.
                content = (p.value, p.status, attrs)
                if key not in first_seen:
                    _, end, _ = parse_period(p.period_label)
                    t = min(
                        release_time(end, parse_lag_days(lag[snap.dataset_id])), snap.retrieved_at
                    )
                    first_seen[key] = (t, content)
                elif first_seen[key][1] == content:
                    continue
            ev = Event(t, None if p.withdrawn else p.value, p.status, attrs, snap.snapshot_id)
            events[key].append(ev)
            if rule in DENSE_RULES and not p.withdrawn:
                vintages[p.series_key].add(t)

    # series rows
    unknown_regions = set()
    rows_series = []
    for skey, p in series_meta.items():
        region = aliases.get((system, p.region_src)) if p.region_src else None
        if p.region_src and region is None:
            unknown_regions.add(p.region_src)
        rows_series.append(
            (
                stable_uuid(family, skey),
                family,
                skey,
                json.dumps(p.dims),
                region,
                p.freq,
                p.unit,
                p.title,
                rule,
            )
        )
    if unknown_regions:
        raise RuntimeError(
            f"{family}: unmapped region codes {sorted(unknown_regions)}; add ref.region_alias"
        )

    # intervals
    rows_obs = []
    for (skey, label), evs in events.items():
        start, end, _ = parse_period(label)
        dense = vintages[skey] if rule in DENSE_RULES else None
        for iv in collapse(evs, dense):
            rows_obs.append(
                (
                    stable_uuid(family, skey),
                    f"[{start},{end})",
                    label,
                    iv.value,
                    iv.status,
                    json.dumps(dict(iv.attrs)) if iv.attrs else None,
                    iv.known_from,
                    iv.known_to,
                    PRECISION[rule],
                    iv.snapshot_id,
                )
            )

    with conn.transaction():
        cur = conn.cursor()
        cur.executemany(
            """INSERT INTO obs.series (series_id, family, series_key, dims, region_code, freq, unit,
                   title, knowledge_rule) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (series_id) DO UPDATE SET dims=EXCLUDED.dims, region_code=EXCLUDED.region_code,
                   freq=EXCLUDED.freq, unit=EXCLUDED.unit, title=EXCLUDED.title,
                   knowledge_rule=EXCLUDED.knowledge_rule""",
            rows_series,
        )
        cur.execute(
            """CREATE TEMP TABLE stage (LIKE obs.observation INCLUDING DEFAULTS) ON COMMIT DROP;
               ALTER TABLE stage DROP COLUMN known;"""
        )
        cols = (
            "series_id, period, period_label, value, obs_status, attrs, known_from, known_to, "
            "knowledge_precision, snapshot_id"
        )
        with cur.copy(f"COPY stage ({cols}) FROM STDIN") as copy:
            for r in rows_obs:
                copy.write_row(r)
        family_filter = "series_id IN (SELECT series_id FROM obs.series WHERE family = %(f)s)"
        same = """st.series_id = o.series_id AND st.period = o.period AND st.known_from = o.known_from"""
        cur.execute(
            f"""DELETE FROM obs.observation o WHERE {family_filter} AND NOT EXISTS (
                    SELECT 1 FROM stage st WHERE {same} AND st.value = o.value
                      AND st.obs_status IS NOT DISTINCT FROM o.obs_status
                      AND st.attrs IS NOT DISTINCT FROM o.attrs)""",
            {"f": family},
        )
        deleted = cur.rowcount
        cur.execute(
            f"""UPDATE obs.observation o SET known_to = st.known_to,
                       knowledge_precision = st.knowledge_precision, snapshot_id = st.snapshot_id
                FROM stage st WHERE {same}
                  AND (o.known_to IS DISTINCT FROM st.known_to OR o.snapshot_id <> st.snapshot_id
                       OR o.knowledge_precision <> st.knowledge_precision)"""
        )
        updated = cur.rowcount
        cur.execute(
            f"""INSERT INTO obs.observation ({cols})
                SELECT {cols} FROM stage ON CONFLICT (series_id, period, known_from) DO NOTHING"""
        )
        inserted = cur.rowcount
        cur.execute(
            "UPDATE raw.snapshot SET load_status='loaded', load_note=NULL WHERE snapshot_id = ANY(%s)",
            ([s.snapshot_id for s in snaps],),
        )
    return {
        "series": len(rows_series),
        "intervals": len(rows_obs),
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
    }


def build(conn: psycopg.Connection, verbose: bool = True) -> dict[str, dict[str, int]]:
    # Autocommit so each conn.transaction() block is a real transaction (one per family).
    conn.autocommit = True
    migrate(conn)
    datasets = sync_cards(conn)
    snaps = register_snapshots(conn, datasets)
    aliases = {
        (s, c): r
        for s, c, r in conn.execute(
            "SELECT system, source_code, region_code FROM ref.region_alias"
        ).fetchall()
    }
    families: dict[str, list[Snap]] = defaultdict(list)
    for s in snaps:
        if not s.skip_reason:
            families[datasets[s.dataset_id]["family"]].append(s)
    report = {}
    for family in sorted(families):
        started = time.time()
        report[family] = build_family(conn, family, families[family], datasets, aliases)
        if verbose:
            r = report[family]
            print(
                f"{family:<45} series={r['series']:>4} intervals={r['intervals']:>7} "
                f"+{r['inserted']} ~{r['updated']} -{r['deleted']}  {time.time() - started:.1f}s"
            )
    skipped = [s for s in snaps if s.skip_reason]
    if verbose and skipped:
        for s in skipped:
            print(f"skipped {s.path.name}: {s.skip_reason}")
    return report


if __name__ == "__main__":
    with connect() as c:
        build(c, verbose="-q" not in sys.argv)
