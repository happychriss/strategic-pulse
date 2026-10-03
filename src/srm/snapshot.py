"""Raw snapshot archive.

Every pull from an upstream source is stored byte-for-byte, with a metadata sidecar
(URL, retrieval time, status, hash). Snapshots are the durable layer: the database can
always be rebuilt from them. Nothing here interprets the data.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
COMPRESS_ABOVE = 1_000_000  # bytes; larger payloads are stored gzip-compressed, losslessly
USER_AGENT = "strategic-regime-monitor/0.0.1 (research; contact via repository)"


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    path: Path
    meta_path: Path
    sha256: str
    size: int
    unchanged: bool = False  # True when identical to the latest archived snapshot (nothing written)


def _ssl_context() -> ssl.SSLContext:
    bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()


def _looks_like(kind: str, body: bytes) -> bool:
    head = body[:2000].lstrip().lower()
    if kind == "csv":
        return not head.startswith((b"<", b"{")) and b"," in head
    if kind == "json":
        # Providers such as Eurostat return error messages as valid JSON with HTTP 200.
        compact = head.replace(b" ", b"")
        # Error messages arrive as valid JSON with HTTP 200, and an empty JSON-stat dataset
        # ("value":{}) means the filter matched nothing; neither is worth archiving.
        return (
            head.startswith((b"{", b"["))
            and not compact.startswith(b'{"error"')
            and b'"value":{}' not in compact
        )
    if kind == "html":
        return b"<html" in head or b"<!doctype html" in head
    if kind == "xml":
        return head.startswith(b"<") and b"<html" not in head
    return True


def fetch(
    card_id: str,
    label: str,
    url: str,
    kind: str,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    timeout: int = 180,
    raw_dir: Path = RAW_DIR,
    skip_unchanged: bool = True,
) -> Snapshot:
    """Download `url` and archive it under data/raw/<card_id>/. `kind` is csv, json or xml.

    A response that does not look like `kind` (for example an HTML error page from a web
    firewall served with HTTP 200) is rejected and never archived.
    """
    req_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error = "no attempt"
    for attempt in range(1, retries + 1):
        retrieved = datetime.now(UTC)
        try:
            request = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as resp:
                body = resp.read()
                status = resp.status
                resp_headers = dict(resp.headers.items())
        except Exception as exc:  # noqa: BLE001 - recorded and retried
            last_error = f"attempt {attempt}: {exc}"
            continue
        if not _looks_like(kind, body):
            last_error = f"attempt {attempt}: response is not {kind} (first bytes {body[:60]!r})"
            continue
        digest = hashlib.sha256(body).hexdigest()
        folder = raw_dir / card_id
        if skip_unchanged:
            previous = latest_snapshot(card_id, label, raw_dir)
            if previous and previous[1] == digest:
                meta = previous[0]
                data_path = meta.with_name(meta.name.removesuffix(".meta.json"))
                return Snapshot(data_path, meta, digest, len(body), unchanged=True)
        stamp = retrieved.strftime("%Y%m%dT%H%M%SZ")
        folder.mkdir(parents=True, exist_ok=True)
        compressed = len(body) > COMPRESS_ABOVE
        path = folder / f"{stamp}__{label}.{kind}{'.gz' if compressed else ''}"
        path.write_bytes(gzip.compress(body, mtime=0) if compressed else body)
        meta_path = path.with_name(path.name + ".meta.json")
        meta_path.write_text(
            json.dumps(
                {
                    "card_id": card_id,
                    "label": label,
                    "url": _redact(url),
                    "retrieved_at_utc": retrieved.isoformat(),
                    "http_status": status,
                    "bytes": len(body),
                    "sha256": digest,
                    "stored_compression": "gzip" if compressed else None,
                    "response_headers": {
                        k: v
                        for k, v in resp_headers.items()
                        if k.lower() in {"content-type", "last-modified", "etag", "date"}
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return Snapshot(path=path, meta_path=meta_path, sha256=digest, size=len(body))
    raise SnapshotError(f"{card_id}/{label}: {last_error}")


def latest_snapshot(card_id: str, label: str, raw_dir: Path = RAW_DIR) -> tuple[Path, str] | None:
    """(meta path, sha256) of the most recent archived snapshot for a card and label."""
    metas = sorted((raw_dir / card_id).glob(f"*__{label}.*.meta.json"))
    if not metas:
        return None
    return metas[-1], json.loads(metas[-1].read_text(encoding="utf-8"))["sha256"]


def _redact(url: str) -> str:
    """Never write tokens into metadata."""
    return re.sub(r"(securityToken|api_key|token)=[^&]+", r"\1=REDACTED", url)
