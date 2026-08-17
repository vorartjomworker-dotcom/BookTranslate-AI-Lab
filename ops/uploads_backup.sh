#!/usr/bin/env bash
set -euo pipefail

umask 077

backup_dir="${BACKUP_DIR:-backups/uploads}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="${1:-${backup_dir}/booktranslate-uploads-${timestamp}.tar.gz}"
partial="${output}.partial"
checksum="${output}.sha256"

mkdir -p "$(dirname "$output")"
rm -f "$partial"

cleanup() {
  rm -f "$partial"
}
trap cleanup EXIT

docker compose run --rm --no-deps -T backend python - <<'PY' > "$partial"
import os
import sys
import tarfile

root = os.environ.get("UPLOAD_DIR", "/var/lib/booktranslate/uploads")
os.makedirs(root, exist_ok=True)

with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz", compresslevel=6) as archive:
    for name in sorted(os.listdir(root)):
        archive.add(os.path.join(root, name), arcname=name, recursive=True)
PY

test -s "$partial"

# Validate paths and reject link entries before publishing the archive.
docker compose run --rm --no-deps -T backend python -c '
import pathlib, sys, tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
    for member in archive:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise SystemExit(f"unsafe archive member: {member.name}")
' < "$partial"

mv "$partial" "$output"
sha256sum "$output" > "$checksum"
trap - EXIT

echo "Uploads backup created: $output"
echo "SHA-256 manifest created: $checksum"
