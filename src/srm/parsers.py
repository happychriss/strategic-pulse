"""Parsers turn one raw snapshot into publication points. They never interpret values."""

from __future__ import annotations

import csv
import gzip
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class Point:
    series_key: str
    dims: dict[str, str]
    region_src: str | None
    freq: str | None
    unit: str | None
    title: str | None
    period_label: str
    value: Decimal | None
    status: str | None
    attrs: dict[str, str] | None
    vintage: str | None  # VALID_FROM / revdate / edition, as published
    withdrawn: bool = False


def read_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def _dec(text: str | None) -> Decimal | None:
    if text is None or text == "" or text.lower() == "nan":
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_ecb_csv(path: Path) -> Iterator[Point]:
    """ECB csvdata. With includeHistory, rows carry ACTION, VALID_FROM and VALID_TO."""
    rows = csv.DictReader(io.StringIO(read_bytes(path).decode("utf-8")))
    header = rows.fieldnames or []
    dim_cols = header[header.index("KEY") + 1 : header.index("TIME_PERIOD")]
    history = "ACTION" in header
    for row in rows:
        dims = {c: row[c] for c in dim_cols}
        common = {
            "series_key": row["KEY"],
            "dims": dims,
            "region_src": dims.get("REF_AREA"),
            "freq": dims.get("FREQ"),
            "unit": row.get("UNIT") or None,
            "title": row.get("TITLE") or None,
            "period_label": row["TIME_PERIOD"],
            "attrs": None,
        }
        if history and row["ACTION"] == "Delete":
            yield Point(**common, value=None, status=None, vintage=row["VALID_TO"], withdrawn=True)
            continue
        value = _dec(row["OBS_VALUE"])
        if value is None:
            continue
        yield Point(
            **common,
            value=value,
            status=row.get("OBS_STATUS") or None,
            vintage=row["VALID_FROM"] if history else None,
        )


def parse_eurostat_jsonstat(path: Path) -> Iterator[Point]:
    """Eurostat JSON-stat 2.0. A 'revdate' dimension, when present, is the vintage."""
    d = json.loads(read_bytes(path), parse_float=Decimal, parse_int=Decimal)
    ids: list[str] = d["id"]
    sizes = [int(s) for s in d["size"]]
    if 0 in sizes:
        return
    codes = []
    for dim in ids:
        index = d["dimension"][dim]["category"]["index"]
        if isinstance(index, list):
            codes.append(list(index))
        else:
            ordered = sorted(index.items(), key=lambda kv: int(kv[1]))
            codes.append([code for code, _ in ordered])
    strides, acc = [0] * len(ids), 1
    for i in reversed(range(len(ids))):
        strides[i] = acc
        acc *= sizes[i]
    status = d.get("status") or {}
    key_dims = [dim for dim in ids if dim not in ("time", "revdate")]
    values = d["value"]
    items = values.items() if isinstance(values, dict) else enumerate(values)
    for flat, value in items:
        if value is None:
            continue
        flat = int(flat)
        coord = {dim: codes[i][(flat // strides[i]) % sizes[i]] for i, dim in enumerate(ids)}
        dims = {dim: coord[dim] for dim in key_dims}
        flag = status.get(str(flat)) if isinstance(status, dict) else None
        yield Point(
            series_key="|".join(f"{k}={dims[k]}" for k in key_dims),
            dims=dims,
            region_src=dims.get("geo"),
            freq=dims.get("freq"),
            unit=dims.get("unit"),
            title=d.get("label"),
            period_label=coord["time"],
            value=Decimal(value),
            status=flag or None,
            attrs=None,
            vintage=coord.get("revdate"),
        )


OECD_ATTRS = ("UNIT_MULT", "BASE_PER")


def parse_oecd_csv(path: Path) -> Iterator[Point]:
    """OECD SDMX csv. The EDITION dimension is the vintage; base period travels as attribute."""
    rows = csv.DictReader(io.StringIO(read_bytes(path).decode("utf-8")))
    header = rows.fieldnames or []
    dim_cols = [c for c in header[1 : header.index("TIME_PERIOD")] if c != "EDITION"]
    for row in rows:
        value = _dec(row["OBS_VALUE"])
        if value is None:
            continue
        dims = {c: row[c] for c in dim_cols}
        attrs = {a: row[a] for a in OECD_ATTRS if row.get(a)}
        yield Point(
            series_key="|".join(f"{k}={dims[k]}" for k in dim_cols),
            dims=dims,
            region_src=dims.get("REF_AREA"),
            freq=dims.get("FREQ"),
            unit=dims.get("UNIT_MEASURE"),
            title=" / ".join(dims.values()),
            period_label=row["TIME_PERIOD"],
            value=value,
            status=row.get("OBS_STATUS") or None,
            attrs=attrs or None,
            vintage=row["EDITION"],
        )


PARSERS = {
    "ecb_csv": parse_ecb_csv,
    "eurostat_jsonstat": parse_eurostat_jsonstat,
    "oecd_csv": parse_oecd_csv,
}
