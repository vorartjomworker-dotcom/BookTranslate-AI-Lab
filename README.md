# BookTranslate AI Lab

BookTranslate AI Lab is a production-oriented advanced MVP for translating technical books. It combines document ingestion, deterministic segmentation, pluggable AI providers, durable background translation jobs, quality evaluation, benchmarking, a translation editor, and local authentication/RBAC.

## Core workflow

`DOCX/EPUB upload → validation/parsing → chapters/segments → translation jobs → AI provider → QA → benchmark/editor`

Implemented capabilities:

- DOCX and EPUB ingestion with archive/file validation
- deterministic chapter and segment persistence in PostgreSQL
- OpenAI, Anthropic, and DeepL provider abstraction
- PostgreSQL-backed translation job state with authenticated Redis Streams delivery
- async translation worker with retry/idempotency/stale-response protection
- deterministic and AI-assisted quality evaluation
- benchmark execution engine
- Next.js operational workspace and translation editor
- local email/password authentication with `viewer`, `editor`, and `admin` roles
- Redis-backed login throttling and durable security audit trail
- liveness/readiness endpoints and Docker Compose deployment validation
- checksummed PostgreSQL/uploads backup helpers with CI-tested restore round trips

## Architecture

### Backend

- Python 3.12
- FastAPI
- SQLAlchemy 2 async ORM
- PostgreSQL 17
- Alembic migrations
- Redis 7 / Redis Streams with password authentication in local Compose
- Argon2id password hashing
- HS256 short-lived JWT access tokens

### Frontend

- Next.js 16.3.1
- React 19.2.8
- TypeScript 5.9
- Vitest + Testing Library

### Containers

The backend image includes the Alembic migration tree and runs as an unprivileged `booktranslate` user. The frontend uses a multi-stage production build, installs dependencies reproducibly with `npm ci`, builds with `next build`, and runs with `npm start` as the unprivileged Node user. Python and Node base images are pinned as `tag@sha256` for reproducible builds, while Dependabot remains responsible for proposing digest updates.

## Quick start with Docker Compose

### 1. Configure the environment

```bash
cp .env.example .env
```

`JWT_SECRET`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD` are intentionally empty in `.env.example`. Generate three independent URL-safe local values:

```bash
python -c "import secrets; print('JWT_SECRET='+secrets.token_urlsafe(48)); print('POSTGRES_PASSWORD='+secrets.token_urlsafe(32)); print('REDIS_PASSWORD='+secrets.token_urlsafe(32))"
```

Copy all three generated values into `.env`. Do not commit `.env`, reuse these values across environments, or use development secrets in production.

AI provider keys are optional unless the corresponding live provider is used.

### 2. Start the stack

```bash
docker compose up --build
```

Compose starts PostgreSQL first, then runs the one-shot `migrate` service with:

```bash
alembic upgrade head
```

The backend and translation worker start only after migrations complete successfully. The frontend waits for a healthy backend. The local Redis service requires `REDIS_PASSWORD`; backend and worker receive an authenticated Redis URL derived from that value.

Local endpoints:

- frontend: `http://localhost:3000`
- backend: `http://localhost:8000`
- PostgreSQL: `127.0.0.1:5432`
- Redis: `127.0.0.1:6379`

PostgreSQL and Redis are bound only to localhost in the development Compose file rather than all host interfaces. Redis also requires authentication even on this localhost binding.

### 3. Verify health

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

`/health/live` is process liveness and does not depend on PostgreSQL or Redis.

`/health/ready` returns `200` only when:

- PostgreSQL is reachable;
- the database `alembic_version` exactly matches the Alembic head(s) shipped with the running backend image; and
- authenticated Redis connectivity succeeds.

A stale or missing database schema therefore makes readiness fail with `503` even if PostgreSQL still accepts `SELECT 1`.

`/health` is retained as a compatibility endpoint and reports `ok`/`degraded` without exposing credentials or connection strings.

### 4. Create the first administrator

After readiness succeeds:

```bash
docker compose exec -it backend python -m app.auth.bootstrap_admin
```

Enter the administrator email and password interactively. This CLI is the only first-administrator/recovery path; there is no public bootstrap HTTP endpoint.

Concurrent bootstrap attempts are serialized in PostgreSQL, and the ordinary admin API prevents demoting or deactivating the last active administrator.

### 5. Log in

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"<admin-password>"}'
```

The response contains a short-lived Bearer access token. The browser keeps this token in memory only; there is no refresh token, authentication cookie, `localStorage`, or `sessionStorage` persistence.

For a temporary shell session:

```bash
export TOKEN="<access_token>"
```

Do not store access tokens in `.env`, files, or persistent shell configuration.

## Authentication and RBAC

Passwords are hashed with Argon2id. JWT signing is HS256-only, `JWT_SECRET` is mandatory, and the configured secret must contain at least 32 characters.

| Capability | `viewer` | `editor` | `admin` |
|---|---:|---:|---:|
| Read books/chapters/segments/jobs/QA/benchmarks | Yes | Yes | Yes |
| Upload and create/update translation content | No | Yes | Yes |
| Run translation jobs and QA | No | Yes | Yes |
| Create/resume persisted dry-run benchmarks | No | Yes | Yes |
| Create/resume live-provider benchmarks | No | No | Yes |
| Cancel benchmarks | No | No | Yes |
| Delete protected resources | No | No | Yes |
| Manage users/roles/active state | No | No | Yes |

Server-side authorization is the security boundary; hiding controls in the frontend is only a UX measure.

### Login throttling

`POST /api/v1/auth/login` is protected by Redis-backed throttling:

- maximum 5 login attempts per normalized account identity per 60 seconds;
- maximum 30 login attempts per client IP per 60 seconds;
- exceeded limits return `429` with `Retry-After`;
- raw email addresses and IP addresses are not stored in Redis rate-limit keys; identifiers are HMAC-SHA256 derived using the application secret;
- if Redis is unavailable, login throttling fails closed with `503` rather than silently bypassing protection.

The rate limiter is request throttling, not a durable account-lockout system.

### Durable security audit trail

Alembic migration `007` adds the durable `audit_events` table. Security-sensitive events include login success/failure/rate-limit/dependency failures, administrator user creation/update and last-admin denials, destructive book/chapter/segment deletion, and benchmark create/resume/cancel operations.

Audit entries carry actor/action/outcome/target/request ID and safe structured details. Raw passwords, JWTs, email addresses, client IP addresses, and benchmark cancellation text are not copied into audit details; identity/source identifiers use HMAC-derived hashes where required.

Administrators can read the append-only application audit feed through `/api/v1/admin/audit-events`.

## Protected API example

Upload requires an `editor` or `admin` token:

```bash
curl -X POST "http://localhost:8000/api/v1/books/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/chapter.docx" \
  -F "title=Example Book" \
  -F "author=Jane Author" \
  -F "language=en"
```

Supported upload formats: `.docx` and `.epub`. Default maximum upload size is 25 MB.

## Backup and recovery

The repository contains guarded helpers for both authoritative PostgreSQL data and the uploaded DOCX/EPUB volume:

```bash
bash ops/postgres_backup.sh
bash ops/uploads_backup.sh
```

Generated backups include SHA-256 manifests and `backups/` is ignored by Git. PostgreSQL dumps are validated with `pg_restore --list`; uploads archives are path-validated and reject symbolic/hard links.

A PostgreSQL restore defaults to a separate verification database. In-place replacement requires explicit `ALLOW_IN_PLACE_RESTORE=YES` plus an exact database-name confirmation. Upload restoration similarly requires `ALLOW_UPLOAD_RESTORE=YES` and uses a staging directory before replacing existing files.

See `ops/README.md` for the complete disaster-recovery runbook, off-host storage requirements, RPO/RTO guidance, restore drills, and optional PostgreSQL PITR/WAL guidance.

## Development without Docker

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

`requirements.txt` contains development/test dependencies. `requirements-runtime.txt` is the smaller runtime dependency set used by the backend Docker image.

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

Useful frontend checks:

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

### Backend tests

```bash
cd backend
pytest tests/ -v
```

GitHub Actions additionally runs PostgreSQL and Redis integration coverage and Alembic migrations.

## CI guarantees

The Docker Compose validation workflow verifies more than YAML syntax. It checks that:

- `JWT_SECRET`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD` are required;
- Redis starts with `--requirepass` and application services derive their Redis URL from the configured password;
- unauthenticated Redis `PING` does not succeed while authenticated `PING` returns `PONG`;
- the migration service executes `alembic upgrade head`;
- backend and worker wait for successful migrations;
- the frontend receives `NEXT_PUBLIC_API_URL` at build time;
- Docker build contexts exclude local `.env`, dependency directories, and build caches;
- a clean Docker deployment can build and start the production frontend/backend stack;
- `/health/ready` succeeds at the current Alembic head;
- forcing a stale Alembic revision makes readiness return `503` and restoring the current head recovers readiness;
- Hadolint is a blocking Dockerfile gate for warning/error findings.

The dedicated `Backup & Restore Validation` workflow additionally creates real PostgreSQL and uploads sentinel data, creates checksummed backups, proves destructive restores are guarded, restores PostgreSQL into an isolated database, validates the restored Alembic revision/data, restores the uploads volume, and confirms backend readiness afterward.

## Security and deployment notes

The repository is an advanced MVP / pre-production platform, not a finished production deployment. Before public or high-value production use, remaining work includes at least:

- GitHub branch protection/rulesets and required review/status gates;
- durable account lockout policy if required by the deployment threat model;
- password reset/recovery workflow beyond administrator CLI recovery;
- server-side session/token revocation if immediate revocation is required;
- TLS for Redis traffic or a managed private Redis service for production deployments;
- production secret management rather than local `.env` files;
- production backup scheduling, off-host encrypted retention, monitoring, and PITR if required by RPO/RTO targets;
- metrics, centralized structured logs, tracing, and alerting;
- multi-tenant isolation if the product will host independent organizations.

The local Compose file keeps PostgreSQL and Redis reachable on localhost for development convenience. Production deployments should normally keep data services on private networks without host-published database/cache ports and should use encrypted transport where required.

## License

MIT
