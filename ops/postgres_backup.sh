#!/usr/bin/env bash
set -euo pipefail

umask 077

backup_dir="${BACKUP_DIR:-backups/postgres}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="${1:-${backup_dir}/booktranslate-${timestamp}.dump}"
partial="${output}.partial"
checksum="${output}.sha256"

mkdir -p "$(dirname "$output")"
rm -f "$partial"

cleanup() {
  rm -f "$partial"
}
trap cleanup EXIT

if ! docker compose exec -T postgres true >/dev/null 2>&1; then
  echo "PostgreSQL Compose service is not running." >&2
  exit 1
fi

# Custom-format archives support pg_restore validation and selective recovery.
docker compose exec -T postgres sh -ec \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=6 --no-owner --no-acl' \
  > "$partial"

test -s "$partial"

# Refuse to publish an archive that pg_restore cannot parse.
docker compose exec -T postgres pg_restore --list < "$partial" >/dev/null

mv "$partial" "$output"
sha256sum "$output" > "$checksum"
trap - EXIT

echo "PostgreSQL backup created: $output"
echo "SHA-256 manifest created: $checksum"
