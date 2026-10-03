"""Archive the source documents cited by model evidence claims (skips existing ones)."""

from __future__ import annotations

import sys

import yaml

from srm.documents import DOCS_DIR
from srm.snapshot import SnapshotError, fetch

MODEL_DIR = DOCS_DIR.parents[2] / "model"


def main() -> int:
    docs = yaml.safe_load((MODEL_DIR / "documents.yaml").read_text(encoding="utf-8"))["documents"]
    failures = 0
    for d in docs:
        if (DOCS_DIR / d["id"]).exists() and any((DOCS_DIR / d["id"]).glob("*.meta.json")):
            print(f"SKIP {d['id']}")
            continue
        try:
            snap = fetch(d["id"], "document", d["url"], "html", raw_dir=DOCS_DIR)
            print(f"OK   {d['id']}  {snap.size:,} B")
        except SnapshotError as exc:
            failures += 1
            print(f"FAIL {d['id']}  {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
