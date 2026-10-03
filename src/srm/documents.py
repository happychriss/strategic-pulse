"""Documentary evidence: archived source documents and verbatim passage checks."""

from __future__ import annotations

import html
import re
from pathlib import Path

from srm.parsers import read_bytes
from srm.snapshot import RAW_DIR

DOCS_DIR = RAW_DIR / "documents"

_DROP = re.compile(
    r"<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalize(text: str) -> str:
    """Whitespace- and typography-insensitive form used to compare passages with sources."""
    return _WS.sub(" ", text.translate(_QUOTES)).strip()


def html_to_text(raw: bytes) -> str:
    page = raw.decode("utf-8", errors="replace")
    main = re.search(r"<main\b.*?</main>", page, re.DOTALL | re.IGNORECASE)
    page = main.group(0) if main else page
    page = _DROP.sub(" ", page)
    return normalize(html.unescape(_TAG.sub(" ", page)))


def latest_document_file(doc_id: str) -> Path:
    files = [p for p in (DOCS_DIR / doc_id).glob("*") if not p.name.endswith(".meta.json")]
    if not files:
        raise FileNotFoundError(f"no archived file for document {doc_id}")
    return max(files)


def document_text(doc_id: str) -> str:
    return html_to_text(read_bytes(latest_document_file(doc_id)))


def passage_in_document(passage: str, doc_id: str) -> bool:
    return normalize(passage) in document_text(doc_id)
