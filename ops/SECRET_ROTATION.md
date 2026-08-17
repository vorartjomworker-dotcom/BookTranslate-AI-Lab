# Secret rotation runbook

This runbook covers production rotation for BookTranslate AI credentials delivered through the validated `*_FILE` configuration interface.

It is intentionally provider-neutral. The deployment platform is responsible for mounting the files from its selected secret store. Application processes read settings only at process startup; changing a mounted file does **not** hot-reload an already-running backend or translator worker.

## Supported file-backed application secrets

| Direct setting | File-backed setting | Main consumers | Rotation effect |
|---|---|---|---|
| `JWT_SECRET` | `JWT_SECRET_FILE` | backend, translator worker, migration jobs that import application settings | New JWT signing key. Existing access tokens signed with the old key become invalid after the backend restarts. |
| `DATABASE_URL` | `DATABASE_URL_FILE` | backend, translator worker, migration jobs | New PostgreSQL credentials/endpoint are used after restart/redeploy. |
| `REDIS_URL` | `REDIS_URL_FILE` | backend, translator worker | New Redis credentials/endpoint are used after restart/redeploy. `REDIS_TLS_REQUIRED=true` still requires `rediss://`. |
| `METRICS_BEARER_TOKEN` | `METRICS_BEARER_TOKEN_FILE` | backend and metrics scraper/client | `/metrics` authentication changes after backend restart. The scraper must be updated coherently. |
| `OPENAI_API_KEY` | `OPENAI_API_KEY_FILE` | backend/worker paths that use OpenAI | New provider key is used after restart/redeploy. |
| `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY_FILE` | backend/worker paths that use Anthropic | New provider key is used after restart/redeploy. |
| `DEEPL_API_KEY` | `DEEPL_API_KEY_FILE` | backend/worker paths that use DeepL | New provider key is used after restart/redeploy. |

Do not configure both a direct setting and its corresponding `*_FILE` setting. The application rejects this ambiguity at startup.

## General rotation sequence

Use this order whenever the upstream service supports overlapping credentials:

1. **Create/provision the replacement credential upstream.** Keep the old credential valid during the cutover.
2. **Publish a new secret version in the deployment secret store.** Do not place the value in Git, `.env`, command history, ticket text, CI logs, or chat transcripts.
3. **Update the mounted secret reference/revision.** Prefer the orchestrator's atomic secret projection or a new immutable secret object/version rather than editing a file in place inside a running container.
4. **Validate configuration in a one-shot/canary process using the same image, mounts, and non-secret configuration.** The validation process must not also receive the direct twin environment variable. A successful import of `app.core.config.settings` proves parsing/policy validation only; it does not prove the external dependency accepts the new credential.
5. **Restart/redeploy all affected long-running processes.** A file update alone is insufficient because settings are loaded at process startup.
6. **Verify application health and the affected dependency path.** Use `/health/live` and `/health/ready`, then a bounded functional check relevant to the rotated secret.
7. **Confirm all production instances are running the new deployment/secret revision.** Do not revoke the old credential while any old instance can still receive traffic or jobs.
8. **Revoke/delete the old upstream credential.** Then repeat the relevant health/functional check.
9. **Record the rotation metadata** (secret name, old/new version identifiers, time, operator/change record, verification result) without recording the secret value.

If the upstream system supports only one active credential, treat the change as a coordinated maintenance operation because a zero-downtime dual-credential cutover may not be possible.

## Pre-rotation safety checks

Before changing a credential:

- confirm the current deployment is healthy;
- confirm the secret store has a recoverable previous version or other rollback mechanism;
- identify every consumer from the table above;
- ensure the replacement credential has the minimum required privileges;
- ensure the mounted file is readable by the unprivileged application process but not broadly accessible;
- confirm the deployment does not also inject the corresponding direct environment variable;
- for Redis, confirm a production TLS endpoint is used when `REDIS_TLS_REQUIRED=true`;
- for database/Redis/provider changes, confirm whether the upstream service supports simultaneous old/new credentials.

## JWT secret rotation

`JWT_SECRET` is the signing key for HS256 access tokens. The current application deliberately uses one active signing secret, not a multi-key JWT keyring.

Rotation therefore has an explicit user-visible effect:

1. publish the replacement JWT secret through `JWT_SECRET_FILE`;
2. restart/redeploy backend and any other process that imports the application settings;
3. verify `/health/ready` and login with a test/admin account through the normal protected flow;
4. expect all access tokens signed with the previous JWT secret to be rejected after the backend cutover;
5. users must authenticate again to receive tokens signed by the new key.

Do not attempt a rolling mixed-key backend deployment if requests can be load-balanced between instances using different JWT signing secrets. Without a keyring, a token issued by one instance may fail on another. Use a coordinated cutover or drain old instances before serving traffic with the new key.

The per-user `token_version` mechanism remains useful for user/session revocation, but it does not replace coordinated global JWT signing-key rotation.

## PostgreSQL credential rotation

Prefer a database platform that supports overlapping credentials or a new role/user for rotation:

1. create the replacement least-privilege database credential/role;
2. update `DATABASE_URL_FILE` to the new connection URL;
3. restart/redeploy backend and translator worker; ensure migration jobs use the same new secret before the next schema deployment;
4. verify `/health/ready` and a bounded read/write workflow;
5. confirm no old instances remain;
6. revoke the old database credential/role.

If changing the password of one PostgreSQL role in place, the old password usually stops working immediately. That requires a coordinated cutover and can create a short outage; do not describe it as zero-downtime rotation.

## Redis credential / endpoint rotation

For production, prefer a managed/private Redis service with TLS and overlapping credentials when available:

1. provision the new Redis credential or endpoint;
2. place the complete connection URL in `REDIS_URL_FILE`;
3. keep `REDIS_TLS_REQUIRED=true` for production TLS deployments;
4. restart/redeploy backend and translator worker;
5. verify `/health/ready`, login throttling behavior, and translation queue delivery with a bounded test;
6. confirm all instances use the new secret revision;
7. revoke the old Redis credential.

The local development Compose Redis uses authenticated `redis://` and does not itself provide a TLS server; this runbook does not convert that local service into a production TLS deployment.

## Metrics bearer-token rotation

Coordinate the backend and scraper/monitoring client:

1. provision/update the new `METRICS_BEARER_TOKEN_FILE` value;
2. update the scraper credential so it can use the new token at cutover;
3. restart/redeploy the backend;
4. verify an unauthenticated `/metrics` request remains rejected;
5. verify the scraper can authenticate and ingest metrics with the new token;
6. remove the old token from the secret store/monitoring configuration.

The application accepts one metrics bearer token at a time, so use a coordinated change if the monitoring system cannot update atomically.

## AI provider-key rotation

For OpenAI, Anthropic, or DeepL:

1. create a new provider key with the intended project/account and least privileges available;
2. update the corresponding provider `*_FILE` secret;
3. restart/redeploy every backend/worker process that can invoke that provider;
4. perform only a bounded authorized provider request or existing provider health/translation test;
5. verify no old instances remain;
6. revoke the old provider key at the provider;
7. review provider usage/audit information for unexpected use around the cutover.

Do not make an unbounded live-model call merely to prove secret rotation.

## Rollback

If the new credential causes failures and the old credential is still valid:

1. restore the previous secret-store version/reference;
2. restart/redeploy the affected processes because settings are not hot-reloaded;
3. verify `/health/ready` and the affected functional path;
4. investigate the replacement credential without exposing it in logs or tickets;
5. do not revoke the old credential until a later cutover is verified.

For a JWT secret rollback, remember that tokens issued during the failed cutover may have been signed with the replacement key and will become invalid again when reverting.

## Verification checklist

After each production rotation, record only non-secret results:

- [ ] New secret version/reference deployed.
- [ ] No direct + `*_FILE` duplicate source is configured.
- [ ] Affected processes restarted/redeployed.
- [ ] `/health/live` succeeds.
- [ ] `/health/ready` succeeds.
- [ ] Dependency-specific bounded functional check succeeds.
- [ ] All instances use the intended deployment/secret revision.
- [ ] Old upstream credential revoked after verification.
- [ ] No secret values/paths were emitted into deployment logs, CI logs, tickets, or source control.
- [ ] Rollback reference/version retained according to the organization's secret-retention policy.

## Current limitation

This repository provides and tests the application-side `*_FILE` interface and configuration validation. It does not choose or provision an external secret store, perform secret rotation in that provider, or hot-reload credentials in already-running processes. Those remain deployment/infrastructure responsibilities.
