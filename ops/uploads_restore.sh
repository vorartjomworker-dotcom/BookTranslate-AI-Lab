#!/usr/bin/env bash
set -euo pipefail

archive="${1:-}"
if [[ -z "$archive" ]]; then
  echo "Usage: ALLOW_UPLOAD_RESTORE=YES bash ops/uploads_restore.sh <uploads.tar.gz>" >&2
  exit 2
fi
if [[ ! -f "$archive" ]]; then
  echo "Uploads backup not found: $archive" >&2
  exit 2
fi
if [[ "${ALLOW_UPLOAD_RESTORE:-}" != "YES" ]]; then
  echo "Refusing uploads restore. Set ALLOW_UPLOAD_RESTORE=YES explicitly." >&2
  exit 1
fi

checksum_file="${archive}.sha256"
if [[ -f "$checksum_file" ]]; then
  expected="$(awk 'NR==1 {print $1}' "$checksum_file")"
  actual="$(sha256sum "$archive" | awk '{print $1}')"
  if [[ -z "$expected" || "$expected" != "$actual" ]]; then
    echo "Uploads backup checksum verification failed." >&2
    exit 1
  fi
fi

# Validate the archive before stopping application writers.
docker compose run --rm --no-deps -T backend python -c '
import pathlib, sys, tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
    for member in archive:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise SystemExit(f"unsafe archive member: {member.name}")
' < "$archive"

docker compose stop backend translator-worker >/dev/null || true

restart_writers() {
  docker compose up -d backend translator-worker >/dev/null || true
}
trap restart_writers EXIT

# Restore into a staging directory first. Existing uploads are removed only after
# the complete archive has been extracted successfully.
docker compose run --rm --no-deps -T backend python -c '
import os
import pathlib
import shutil
import sys
import tarfile
import uuid

root = pathlib.Path(os.environ.get("UPLOAD_DIR", "/var/lib/booktranslate/uploads"))
root.mkdir(parents=True, exist_ok=True)
staging = root / (".restore-staging-" + uuid.uuid4().hex)
staging.mkdir()

try:
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
        for member in archive:
            member_path = pathlib.PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts or member.issym() or member.islnk():
                raise RuntimeError(f"unsafe archive member: {member.name}")
            archive.extract(member, path=staging, filter="data")

    for child in list(root.iterdir()):
        if child == staging:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for child in list(staging.iterdir()):
        shutil.move(str(child), str(root / child.name))
finally:
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
' < "$archive"

trap - EXIT
restart_writers

echo "Uploads volume restored from: $archive"
