#!/bin/bash
# SessionStart hook for Claude Code cloud sessions.
# Installs Python deps and a local dev PostgreSQL so tests and ingestion code can run.
# Idempotent and non-interactive. The dev database is disposable: it is rebuilt from
# schema + raw snapshots in git, never treated as the system of record.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# --- Python dependencies (uv, cached in container state) ---
if ! command -v uv >/dev/null 2>&1; then
  pip install --quiet uv
fi
uv sync --quiet

# --- PostgreSQL (Ubuntu apt ships 16; the PG18 temporal features need a container image) ---
if ! command -v pg_ctlcluster >/dev/null 2>&1 || [ -z "$(ls /usr/lib/postgresql 2>/dev/null)" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq postgresql postgresql-contrib >/dev/null
fi

PG_VERSION="$(ls /usr/lib/postgresql | sort -n | tail -1)"
if ! pg_lsclusters -h | awk '{print $4}' | grep -q online; then
  pg_ctlcluster "$PG_VERSION" main start
fi

# Wait for readiness (max ~20 s)
for _ in $(seq 1 20); do
  if su postgres -c "pg_isready -q"; then break; fi
  sleep 1
done

# Dev-only role and database. Local container only, never reuse these credentials elsewhere.
su postgres -c "psql -v ON_ERROR_STOP=1 -qtAc \"SELECT 1 FROM pg_roles WHERE rolname='srm'\"" | grep -q 1 \
  || su postgres -c "psql -v ON_ERROR_STOP=1 -qc \"CREATE ROLE srm LOGIN PASSWORD 'srm' CREATEDB\""
su postgres -c "psql -qtAc \"SELECT 1 FROM pg_database WHERE datname='srm_dev'\"" | grep -q 1 \
  || su postgres -c "createdb -O srm srm_dev"

# --- Session environment ---
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo 'export PYTHONPATH="src:${PYTHONPATH:-}"'
    echo 'export SRM_DATABASE_URL="postgresql://srm:srm@localhost:5432/srm_dev"'
    echo 'export PATH="$CLAUDE_PROJECT_DIR/.venv/bin:$PATH"'
  } >> "$CLAUDE_ENV_FILE"
fi

echo "session-start: python deps ok, postgres ${PG_VERSION} up, db srm_dev ready"
