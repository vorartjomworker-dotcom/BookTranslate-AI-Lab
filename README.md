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
- Redis-backed login throttling, durable PostgreSQL account lockout, and durable security audit trail
- optional fail-closed Redis TLS enforcement requiring `rediss://` when enabled, plus credential-safe Redis endpoint logging
- immediate server-side access-token revocation through per-user token versions
- operator CLI password recovery with lockout clearing and token revocation
- structured JSON HTTP request logging and optional protected Prometheus metrics
- liveness/readiness endpoints and Docker Compose deployment validation
- checksummed PostgreSQL/uploads backup helpers with CI-tested restore round trips

## Architecture

### Backend

- Python 3.12
- FastAPI
- SQLAlchemy 2 async ORM
- PostgreSQL 17
- Alembic migrations
- Redis 7 / Redis Streams with password authentication in local Compose and optional `rediss://` enforcement for production endpoints
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

Local Compose deliberately uses `REDIS_TLS_REQUIRED=false` with authenticated `redis://` traffic on the private Docker network and a localhost-only host binding. For an external or managed production Redis endpoint, set both:

```bash
REDIS_TLS_REQUIRED=true
REDIS_URL=rediss://:<password>@<redis-host>:6380/0
```

When `REDIS_TLS_REQUIRED=true`, application settings fail closed unless `REDIS_URL` uses `rediss://`. Only `redis://` and `rediss://` schemes with a host are accepted. This policy does not provide a TLS server by itself; the configured Redis service must actually support TLS and present a certificate trusted by the runtime.

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

Enter the administrator email and password interactively. This CLI is the only first-administrator bootstrap path; there is no public bootstrap HTTP endpoint.

Concurrent bootstrap attempts are serialized in PostgreSQL, and the ordinary admin API prevents demoting or deactivating the last active administrator.

### 5. Recover an existing account password from the operator CLI

For a known existing account whose password must be replaced:

```bash
docker compose exec -it backend python -m app.auth.reset_password
```

Enter the target email and new password interactively. The reset preserves the account role and active/inactive state, clears durable login lockout state, increments the user's token version so all previously issued access JWTs are immediately invalidated, and writes a durable `auth.password_reset` audit event. The password and raw email are not copied into audit details.

For non-interactive automation, `RESET_USER_EMAIL` and `RESET_USER_PASSWORD` may be supplied to the CLI process through a secure secret-injection mechanism. Do not commit either value or place them in persistent shell history or repository `.env` files.

### 6. Log in

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

To explicitly log out and invalidate all currently issued access tokens for that user:

```bash
curl -i -X POST "http://localhost:8000/api/v1/auth/logout" \
  -H "Authorization: Bearer $TOKEN"
```

A successful logout returns `204 No Content`.

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

This request-level limiter complements the durable account lockout below.

### Durable account lockout

Alembic migration `008` adds `failed_login_attempts` and `locked_until` to users. By default, 10 consecutive invalid passwords lock an account for 15 minutes. Existing-user authentication takes a row lock before changing the counters so concurrent failures cannot lose increments. A successful authentication clears prior failures, and expired locks recover automatically.

The public authentication contract remains intentionally generic for unknown and locked accounts so lock state cannot be used as an account-enumeration signal. The threshold and duration are configurable with `LOGIN_LOCKOUT_THRESHOLD` and `LOGIN_LOCKOUT_MINUTES`. Operator CLI password recovery also clears the target user's durable lockout counters as part of the same transaction as the password replacement.

### Immediate access-token revocation

Alembic migration `009` adds a non-negative per-user `token_version`. Newly issued access JWTs include that version in the `ver` claim; authentication rejects a JWT if its version no longer matches the current user record.

`POST /api/v1/auth/logout` atomically increments `token_version`, immediately invalidating every previously issued access token for the authenticated user. Concurrent revocations use an atomic SQL increment so updates are not lost. Tokens issued before migration `009` without `ver` are treated as version `0` only for migration compatibility and are invalidated by the first revocation.

The operator CLI password-recovery command also increments `token_version` while holding the target user row lock, so a credential reset cannot leave previously issued access tokens valid.

The browser still clears its in-memory identity/workspace state even when the logout request cannot reach the server. Server revocation is therefore best-effort from the browser but authoritative whenever the request succeeds.

### Durable security audit trail

Alembic migration `007` adds the durable `audit_events` table. Security-sensitive events include login success/failure/rate-limit/dependency failures, logout revocation, operator CLI password recovery, administrator user creation/update and last-admin denials, destructive book/chapter/segment deletion, and benchmark create/resume/cancel operations.

Audit entries carry actor/action/outcome/target/request ID and safe structured details. Raw passwords, JWTs, email addresses, client IP addresses, and benchmark cancellation text are not copied into audit details; identity/source identifiers use HMAC-derived hashes where required.

Administrators can read the append-only application audit feed through `/api/v1/admin/audit-events`.

## Observability

HTTP requests are emitted as structured JSON events with bounded metadata: request ID, method, path without query string, response status, and duration. Request bodies, headers, access tokens, client IP addresses, and query-string secrets are not copied into these events.

Redis worker connection logs use a credential-safe endpoint representation: username/password, database path, query string, and fragment are omitted rather than logging `REDIS_URL` verbatim.

Prometheus metrics are optional and disabled by default. When enabled, `/metrics` requires a separate `METRICS_BEARER_TOKEN` of at least 32 characters. HTTP counters and latency histograms use route templates rather than arbitrary raw paths to keep label cardinality bounded.

Production deployments should forward these structured logs and metrics to their selected aggregation/monitoring systems rather than relying only on container-local output.

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
- Redis starts with `--requirepass` and application services derive their local Redis URL from the configured password;
- backend and worker both receive `REDIS_TLS_REQUIRED`, while backend tests enforce that enabling it rejects plaintext `redis://` URLs and requires `rediss://`;
- unauthenticated Redis `PING` does not succeed while authenticated `PING` returns `PONG`;
- the migration service executes `alembic upgrade head`;
- backend and worker wait for successful migrations;
- the frontend receives `NEXT_PUBLIC_API_URL` at build time;
- Docker build contexts exclude local `.env`, dependency directories, and build caches;
- a clean Docker deployment can build and start the production frontend/backend stack;
- `/health/ready` succeeds at the current Alembic head;
- forcing a stale Alembic revision makes readiness return `503` and restoring the current head recovers readiness;
- protected metrics configuration is validated as part of the deployment smoke test;
- Hadolint is a blocking Dockerfile gate for warning/error findings.

The dedicated `Backup & Restore Validation` workflow additionally creates real PostgreSQL and uploads sentinel data, creates checksummed backups, proves destructive restores are guarded, restores PostgreSQL into an isolated database, validates the restored Alembic revision/data, restores the uploads volume, and confirms backend readiness afterward.

## Security and deployment notes

The repository is an advanced MVP / pre-production platform, not a finished production deployment. Before public or high-value production use, remaining work includes at least:

- GitHub branch protection/rulesets and required review/status gates;
- independent PR review before promotion to production;
- self-service or email-mediated password recovery only if the deployment requires it; operator CLI recovery is available;
- provisioning an actual TLS-capable or managed private Redis endpoint in production and enabling `REDIS_TLS_REQUIRED=true`; application-side fail-closed enforcement is available but local Compose does not provide a Redis TLS server;
- production secret management rather than local `.env` files;
- production backup scheduling, off-host encrypted retention, monitoring, and PITR if required by RPO/RTO targets;
- centralized log aggregation, distributed tracing, dashboards, and alerting;
- multi-tenant isolation if the product will host independent organizations.

The local Compose file keeps PostgreSQL and Redis reachable on localhost for development convenience. Production deployments should normally keep data services on private networks without host-published database/cache ports and should use encrypted transport where required.

## License

MIT
