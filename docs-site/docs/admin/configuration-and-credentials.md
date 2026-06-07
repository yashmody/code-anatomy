---
id: configuration-and-credentials
title: Configuration & credentials
sidebar_position: 3
---

# Configuration & credentials

Every environment-specific value — secrets, database URL, OAuth credentials,
cache TTLs — lives in environment variables, never in the database and never in
git. This page is how you set, validate and rotate them.

## Scan box

- **`APP_ENV` is the master switch.** `development`, `staging` or `production`.
  It is set both in `backend/.env` and on the `cca-quiz` systemd unit, and it
  decides how strict boot validation is.
- **Production fails closed.** `validate_for_env()` refuses to boot if a Tier-1
  secret still carries a dev default, or if `ALLOWED_DOMAIN` is empty. That is
  deliberate.
- **Secrets are tiered.** Tier-1 (signing keys, OAuth, SMTP, cert HMAC) must be
  real in production; Tier-2 (cache TTLs, pool sizes) are safe to keep in the
  committed templates.
- **Two planes, two secret files.** The app reads `backend/.env`; Directus reads
  `cms/.env`. Both are gitignored and `chmod 600`. Neither is ever committed.
- **The database link is TLS.** `DATABASE_URL` carries `sslmode=require` at
  minimum (`verify-full` with a CA preferred). Secrets live only in env vars —
  the `signing_keys` table holds metadata, never key material.

## `APP_ENV` and fail-closed boot

`deploy.sh` defaults `APP_ENV` to `production`. The value is written in two
places on purpose: in `backend/.env` (loaded by python-dotenv) and as
`Environment=APP_ENV=...` on the systemd unit (visible in `systemctl show`,
surviving a hand-edited `.env`).

```mermaid
flowchart TD
    B["app boots · reads APP_ENV"] --> D{APP_ENV == development?}
    D -->|yes| Dev["dev defaults allowed<br/>email login (QUIZ_DEV_MODE=true)"]
    D -->|no| C{"Tier-1 secret still a dev default,<br/>or ALLOWED_DOMAIN empty?"}
    C -->|yes| F["refuse to boot<br/>(loud error in journal)"]
    C -->|no| S["start · Google OAuth only"]
```

You cannot accidentally ship production signed with a known dev key — the process
will not start.

## The secret tiers

**Tier-1 — must be real in production** (held as `SecretStr`, never logged):

| Variable | Purpose |
|---|---|
| `SECRET_KEY`, `APP_PAYLOAD_SECRET` | Session and payload signing |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Learner OAuth |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` | Certificate emails |
| `CERT_HMAC_PROD`, `CERT_HMAC_LEGACY` (`_STG` / `_DEV` per env) | Certificate signing |
| `DIRECTUS_ADMIN_TOKEN` | Directus loopback auth |
| `ALLOWED_DOMAIN` | Empty fails boot in production |

**Tier-2 — runtime tunables, safe in templates:**

| Variable | Default |
|---|---|
| `CACHE_TTL_FRAMEWORK` | `900` |
| `CACHE_TTL_FEED` | `30` |
| `CACHE_TTL_APP_CONFIG` | `60` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `5` |
| `ADMIN_EMAILS` | seeded as `platform_admin` |

## The `.env` files

| File | Holds | Notes |
|---|---|---|
| `backend/.env.development.example` / `.staging.example` / `.production.example` | Documented templates | Committed; production template carries no Tier-1 defaults |
| `backend/.env` | The app's real secrets | Gitignored, `chmod 600`, owned by `cca` |
| `cms/.env` | Directus's real secrets | Gitignored, `chmod 600` |
| `deploy.env` | Deploy-time overrides | Root, gitignored |

`deploy.sh` generates fresh `SECRET_KEY` and `APP_PAYLOAD_SECRET` on first
`.env` creation and never overwrites an existing `.env`.

## Database connection (TLS)

```
postgresql://app_prod:****@REMOTE_DB_HOST:5432/codecoder?sslmode=require
```

`verify-full&sslrootcert=/etc/dept-anatomy/db-ca.pem` is preferred where the CA
is provisioned. SQLAlchemy honours the `sslmode` query parameter, so TLS is
enforced from the URL itself — no extra code. The runtime app role
(`app_prod` / `app_dev`) is DML-only.

## Local development

`start_local.sh` mirrors production locally:

```bash
./start_local.sh                        # development (default)
./start_local.sh --env staging          # boot as staging
./start_local.sh --env=production --db   # production env + local Postgres
./start_local.sh --with-cms              # also boot Directus on :8055
```

## Rotation

- **Certificate HMAC keys** rotate carefully — keep the old key verifiable. See
  [Database operations → signing-key rotation](./database-operations#rotating-certificate-signing-keys).
- **`SECRET_KEY`** can rotate independently of the cert keys; it invalidates
  sessions (routine), and because cert signing is decoupled it does *not* break
  issued certificates.
- A pre-commit `gitleaks` hook is recommended so a secret can never be committed.

:::caution[Common Pitfall]

Trusting "the database is on a private network" instead of TLS. A remote
connection without `sslmode=require` is cleartext on the wire — credentials and
every row exposed to anything on the path. Network segmentation is defence in
depth, not a substitute. Keep `sslmode=require` in the URL and confirm with
`psql "$DATABASE_URL" -c "\conninfo"` that it reports an SSL connection.

:::

:::note[Why This Matters]

The v1 risk was a dev-default `SECRET_KEY` silently reaching production.
`deploy.sh` now generates fresh secrets at create time, and the startup check
refuses to run on a dev default. The fail-closed posture turns a quiet,
dangerous misconfiguration into a loud, safe refusal to boot.

:::

For the full security model behind these controls (header ownership, CORS, the
HMAC scheme, payload encryption), see the
[security baseline](../developer/architecture/security-baseline).
