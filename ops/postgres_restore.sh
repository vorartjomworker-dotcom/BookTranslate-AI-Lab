#!/usr/bin/env bash
set -euo pipefail

backup="${1:-}"
if [[ -z "$backup" ]]; then
  echo "Usage: RESTORE_DATABASE=<target> bash ops/postgres_restore.sh <backup.dump>" >&2
  exit 2
fi
if [[ ! -f "$backup" ]]; then
  echo "Backup file not found: $backup" >&2
  exit 2
fi

source_db="$(docker compose exec -T postgres sh -ec 'printf %s "$POSTGRES_DB"')"
source_user="$(docker compose exec -T postgres sh -ec 'printf %s "$POSTGRES_USER"')"
target_db="${RESTORE_DATABASE:-booktranslate_restore_verify}"

if [[ ! "$target_db" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "RESTORE_DATABASE contains unsafe characters: $target_db" >&2
  exit 2
fi

checksum_file="${backup}.sha256"
if [[ -f "$checksum_file" ]]; then
  expected="$(awk 'NR==1 {print $1}' "$checksum_file")"
  actual="$(sha256sum "$backup" | awk '{print $1}')"
  if [[ -z "$expected" || "$expected" != "$actual" ]]; then
    echo "Backup checksum verification failed." >&2
    exit 1
  fi
fi

# Validate archive structure before changing any database.
docker compose exec -T postgres pg_restore --list < "$backup" >/dev/null

in_place=0
if [[ "$target_db" == "$source_db" ]]; then
  in_place=1
  if [[ "${ALLOW_IN_PLACE_RESTORE:-}" != "YES" || "${CONFIRM_DATABASE:-}" != "$source_db" ]]; then
    cat >&2 <<EOF
Refusing in-place restore of '$source_db'.
To perform a destructive restore, set:
  RESTORE_DATABASE=$source_db
  ALLOW_IN_PLACE_RESTORE=YES
  CONFIRM_DATABASE=$source_db
EOF
    exit 1
  fi
  # Prevent application writes while the database is replaced.
  docker compose stop frontend backend translator-worker >/dev/null || true
fi

# Terminate connections, replace the target DB, and restore without archive ownership/ACL metadata.
docker compose exec -T postgres psql -U "$source_user" -d postgres -v ON_ERROR_STOP=1 -v target="$target_db" <<'SQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = :'target' AND pid <> pg_backend_pid();
SELECT format('DROP DATABASE IF EXISTS %I', :'target') \gexec
SELECT format('CREATE DATABASE %I', :'target') \gexec
SQL

docker compose exec -T postgres sh -ec \
  'exec pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --no-acl --exit-on-error' \
  sh "$target_db" < "$backup"

restored_revision="$(docker compose exec -T postgres psql -U "$source_user" -d "$target_db" -Atc 'SELECT version_num FROM alembic_version;' | tr -d '\r')"
if [[ -z "$restored_revision" ]]; then
  echo "Restore completed but alembic_version is missing or empty." >&2
  exit 1
fi

echo "PostgreSQL restore completed into database: $target_db"
echo "Restored Alembic revision: $restored_revision"

if [[ "$in_place" -eq 1 ]]; then
  # Bring restored schema to the code's current migration head before serving traffic.
  docker compose run --rm migrate
  docker compose up -d backend translator-worker frontend
  echo "In-place restore migrated to current head and application services restarted."
fi
