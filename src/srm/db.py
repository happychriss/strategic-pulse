"""Database connection and forward-only migrations."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"
DEFAULT_URL = "postgresql://srm:srm@localhost:5432/srm_dev"


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or os.environ.get("SRM_DATABASE_URL", DEFAULT_URL))


def migrate(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in order. Applied migrations are immutable (hash-checked)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS public.schema_migrations (
               version text PRIMARY KEY, sha256 text NOT NULL,
               applied_at timestamptz NOT NULL DEFAULT now())"""
    )
    conn.commit()
    applied = dict(conn.execute("SELECT version, sha256 FROM public.schema_migrations").fetchall())
    done = []
    for path in sorted(directory.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(sql.encode()).hexdigest()
        if path.stem in applied:
            if applied[path.stem] != digest:
                raise RuntimeError(f"migration {path.name} changed after it was applied")
            continue
        with conn.transaction():
            conn.execute(sql)
            conn.execute(
                "INSERT INTO public.schema_migrations (version, sha256) VALUES (%s, %s)",
                (path.stem, digest),
            )
        done.append(path.stem)
    return done


if __name__ == "__main__":
    if sys.argv[1:] != ["migrate"]:
        raise SystemExit("usage: python -m srm.db migrate")
    with connect() as c:
        print("applied:", migrate(c) or "nothing pending")
