# Backup and recovery runbook

This directory contains guarded backup and restore helpers for the local/pre-production Docker Compose deployment.

## Scope

The durable data that must be protected is:

- PostgreSQL (`postgres_data`) — books, chapters, segments, jobs, QA, benchmarks, users, audit events, and Alembic state.
- Uploaded source documents (`uploads_data`) — DOCX/EPUB files stored under `UPLOAD_DIR`.

Redis is used as queue/cache infrastructure and is not treated as the authoritative system of record for translation job state.

Backups are written with restrictive permissions (`umask 077`) and `backups/` is ignored by Git. A backup is not complete until it has been copied to storage outside the application host and its checksum has been verified there.

## PostgreSQL backup

With the Compose stack running and `.env` configured:

```bash
bash ops/postgres_backup.sh
```

Default output:

```text
backups/postgres/booktranslate-YYYYMMDDTHHMMSSZ.dump
backups/postgres/booktranslate-YYYYMMDDTHHMMSSZ.dump.sha256
```

To choose a destination:

```bash
bash ops/postgres_backup.sh /secure/off-host/booktranslate.dump
```

The helper uses PostgreSQL custom format (`pg_dump --format=custom`), excludes ownership/ACL metadata, validates the archive with `pg_restore --list`, and writes a SHA-256 manifest.

Verify a copied backup before use:

```bash
sha256sum -c /secure/off-host/booktranslate.dump.sha256
```

## PostgreSQL restore verification

Restore into a separate verification database first:

```bash
RESTORE_DATABASE=booktranslate_restore_verify \
  bash ops/postgres_restore.sh /secure/off-host/booktranslate.dump
```

The restore helper validates the checksum when the adjacent `.sha256` file exists, validates archive structure, recreates only the target database, restores with `--no-owner --no-acl --exit-on-error`, and confirms that `alembic_version` exists.

Inspect the restored database before any production recovery:

```bash
docker compose exec -T postgres \
  psql -U booktranslate -d booktranslate_restore_verify \
  -c 'SELECT version_num FROM alembic_version;'
```

## PostgreSQL in-place disaster recovery

An in-place restore is destructive and is refused unless both confirmation variables are present. The helper stops backend and translator-worker before replacing the database, applies current Alembic migrations after restore, then restarts those writers.

```bash
RESTORE_DATABASE=booktranslate \
ALLOW_IN_PLACE_RESTORE=YES \
CONFIRM_DATABASE=booktranslate \
  bash ops/postgres_restore.sh /secure/off-host/booktranslate.dump
```

If `POSTGRES_DB` is customized, use that exact database name in both `RESTORE_DATABASE` and `CONFIRM_DATABASE`.

After recovery, verify:

```bash
curl -fsS http://localhost:8000/health/ready
```

Do not delete the source backup until application-level validation is complete.

## Uploaded documents backup

```bash
bash ops/uploads_backup.sh
```

Default output:

```text
backups/uploads/booktranslate-uploads-YYYYMMDDTHHMMSSZ.tar.gz
backups/uploads/booktranslate-uploads-YYYYMMDDTHHMMSSZ.tar.gz.sha256
```

The archive is generated from the mounted `uploads_data` volume. Archive paths are validated and symbolic/hard links are rejected before the backup is published.

## Uploaded documents restore

Uploads restore is also destructive and requires explicit confirmation:

```bash
ALLOW_UPLOAD_RESTORE=YES \
  bash ops/uploads_restore.sh /secure/off-host/booktranslate-uploads.tar.gz
```

The helper verifies the checksum when present, validates the archive before stopping writers, extracts into a staging directory, and removes the existing upload set only after the complete archive has been extracted successfully. Backend and translator-worker are restarted after the swap.

After restore, verify readiness and open representative source documents through the application.

## Required production policy

The scripts provide a tested recovery mechanism, but a production backup program must additionally define and enforce:

- backup frequency and retention;
- off-host/object-storage destination;
- encryption at rest and in transit;
- access control and key rotation;
- RPO and RTO targets;
- automated monitoring of failed backups;
- periodic restore drills against isolated infrastructure;
- coordinated PostgreSQL + uploads snapshots when strict point-in-time consistency is required;
- optional PostgreSQL WAL/PITR if the deployment requires recovery between scheduled logical dumps.

The GitHub Actions workflow `Backup & Restore Validation` performs an isolated round-trip restore of both PostgreSQL data and the uploads volume so changes to these helpers cannot silently break recovery.
