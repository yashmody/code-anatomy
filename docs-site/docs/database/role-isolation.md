---
id: role-isolation
title: Role isolation
sidebar_position: 4
---

# Role isolation

## Scan box

- **Directus connects as a dedicated, scoped Postgres role** — `directus_app`
  in production — created by `0008_directus_app_role`. The role **name is
  per environment** (`DIRECTUS_DB_ROLE`: `directus_app` for prod,
  `directus_app_dev` for dev) so that on the shared remote instance a dev
  credential cannot reach the prod database. It is *not* the superuser role the
  migrations run as.
- **The role reaches exactly the content and config tables it edits**, with
  per-table granularity: full DML on authoring surfaces, `UPDATE`-only on the
  feed moderation surface, `SELECT`-only on identity and media metadata.
- **Four tables are hard-denied — not even `SELECT`:** `attempts`,
  `quiz_sessions`, `signing_keys`, `auth_audit`. The deny is an explicit
  `REVOKE ALL`, defence against a future migration accidentally widening
  access.
- **This is database-level enforcement**, independent of Directus's own
  application RBAC. Even a compromised Directus instance cannot read a
  certificate row or the audit log, because the database refuses it.

The role and its grants are defined in
`backend/migrations/versions/0008_directus_app_role.py`. The authority for
the matrix is `docs/architecture/v2/03-data-model.md` §5.

## Two layers of authorisation, not one

It is worth being precise about what this role does and does not do.
Directus has its own application-level RBAC — editor accounts, editor roles,
field-level permissions — that governs who can do what *inside the Directus
admin UI*. That is one layer. The `directus_app` Postgres role is a second,
lower layer: it governs what the Directus *process* can do against the
database at all, regardless of which editor is logged in.

The two layers defend different things. Directus RBAC stops an editor from
seeing a collection they should not. The database role stops the entire
Directus service — even if its application layer is misconfigured or
compromised — from touching tables it has no business in. The runtime tables
are protected by the lower layer, where Directus's own configuration cannot
reach.

```
┌─────────────────────────────────────────────────────────────┐
│  Editor (browser)                                            │
│     │                                                         │
│     ▼  Directus application RBAC  ── layer 1 (in-app)        │
│  Directus service                                            │
│     │                                                         │
│     ▼  directus_app DB role       ── layer 2 (in Postgres)  │
│  Postgres                                                    │
│     ├── content/config tables  → granted, per-table          │
│     └── attempts, quiz_sessions,                             │
│         signing_keys, auth_audit → REVOKE ALL (no access)    │
└─────────────────────────────────────────────────────────────┘
```

## The GRANT / REVOKE matrix

`0008` grants `CREATE, USAGE ON SCHEMA public` first — Directus needs to
create and manage its own `directus_*` system tables. Then it applies
per-table grants, and finally an explicit `REVOKE ALL` on the denied set.

| Table | SELECT | INSERT | UPDATE | DELETE | Why |
|---|---|---|---|---|---|
| `users` | yes | — | — | — | Learner identity; read-only view in Directus |
| `roles` | yes | — | — | — | Reference data; labels change via migration |
| `user_roles` | yes | — | — | — | Read-only by default; grant UI is gated behind a 05-config decision |
| `course_chapters` | yes | yes | yes | yes | Content Author surface — full DML |
| `questions` | yes | yes | yes | yes | Official authoring + moderation — full DML |
| `frameworks` | yes | yes | yes | — | Two-row table; rows must never be dropped, so no DELETE |
| `feed_items` | yes | — | yes | — | Moderation only — flips `status`; never creates or removes posts |
| `app_config` | yes | yes | yes | — | Platform Admin config UI; key deletion goes through a migration |
| `media_assets` | yes | — | — | — | Metadata read for the asset browser; bytes are FastAPI-only |
| **`attempts`** | **no** | **no** | **no** | **no** | Runtime + HMAC-sealed; never editor-mutable |
| **`quiz_sessions`** | **no** | **no** | **no** | **no** | Ephemeral runtime state |
| **`signing_keys`** | **no** | **no** | **no** | **no** | Key metadata; Platform-Admin infra path only |
| **`auth_audit`** | **no** | **no** | **no** | **no** | Append-only audit; not even readable by Directus |

The role is also granted `USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public`
so serial-backed inserts (questions, course chapters, config, frameworks)
can draw their identity values.

The grant shape is deliberately asymmetric per table. Three patterns recur:

- **Full DML** on tables editors genuinely author from scratch
  (`course_chapters`, `questions`).
- **No-DELETE** on tables where rows are load-bearing and the runtime
  resolves against exactly those rows (`frameworks` two rows, `app_config`
  keys). Deletion must go through a migration, not the UI.
- **UPDATE-only** on the moderation surface (`feed_items`): a moderator
  flips `status`, but posts are created and removed by the learner runtime,
  never by Directus.

## The hard-denied set

After the grant block, `0008` issues one explicit statement:

```sql
REVOKE ALL ON attempts, quiz_sessions, signing_keys, auth_audit
FROM directus_app;
```

These four tables are the security-sensitive core of the runtime:

- **`attempts`** holds the HMAC-sealed certificate data. An editor must
  never be able to forge, alter, or even read the seal inputs.
- **`quiz_sessions`** holds the server-side answer key for in-flight quizzes
  (`server_answers`). Read access would leak live answers.
- **`signing_keys`** holds certificate key *metadata*. The key material is
  in environment variables and never in the database, but even the metadata
  — which environment is active, which env var names hold the secrets — is
  infra-only.
- **`auth_audit`** is the append-only authorisation log. Only the FastAPI
  runtime writes it; Directus has no reason to read it and no ability to
  truncate it.

:::note[Why This Matters]

The `REVOKE ALL` is not redundant with "we just did not grant these tables".
Grants in Postgres are additive and a future migration that runs a blanket
`GRANT ... ON ALL TABLES IN SCHEMA public` — an easy line to write — would
silently include the new tables and the sensitive ones alike. The explicit
revoke is a standing instruction: these four are off-limits, and the next
person who widens grants has to consciously override it. Security that
survives the next migration is worth the extra line.

:::

## Reversibility and password handling

The migration is additive and reversible. `downgrade()` runs `DROP OWNED BY`
the role (which removes every grant it holds across the database) and then
`DROP ROLE`, both guarded on a `pg_roles` existence check so a re-run is a clean
no-op.

The role is created `LOGIN` but with **no password**, under the name supplied by
`DIRECTUS_DB_ROLE` (defaulting to `directus_app`):

```sql
-- name from DIRECTUS_DB_ROLE: directus_app (prod) | directus_app_dev (dev)
CREATE ROLE directus_app LOGIN;
```

A role with no password cannot actually log in until a password (or other
auth method) is configured. That is intentional: the migration is
environment-agnostic and must not bake a credential into source control. The
operator sets and rotates the password out of band — `deploy.sh` in
production, the local 4a setup for development.

## Per-environment role names on the shared instance

The database now lives on a **remote shared instance** that hosts both the prod
database (`codecoder`) and the dev database (`codecoder_dev`). Data isolation
comes from the separate databases — but credential isolation needs more, because
of how Postgres scopes roles.

A Postgres ROLE is **cluster-global**: it exists once for the whole instance, not
per database. A GRANT, by contrast, is per-database-object. So a *single* role
name GRANTed on both databases would be one credential that reaches both — the
separate databases would not contain it. The isolation therefore depends on a
**distinct role name per environment**, each GRANTed only on its own database:

| Environment | Database | Directus role | FastAPI app role |
|---|---|---|---|
| Production | `codecoder` | `directus_app` | `app_prod` |
| Development | `codecoder_dev` | `directus_app_dev` | `app_dev` |

`0008` reads `DIRECTUS_DB_ROLE`, so running the migration against `codecoder_dev`
with `DIRECTUS_DB_ROLE=directus_app_dev` creates and GRANTs the *dev* Directus
role on the *dev* database, never the prod role. The FastAPI app role is created
out of band by the DBA, also per-env, and is DML-only.

:::caution[Common Pitfall]
Granting `directus_app` (or one `app` role) on **both** `codecoder` and
`codecoder_dev` "because it is the same instance". That single credential then
reaches both databases and dev/prod isolation is gone. Use a distinct role *name*
per environment and GRANT each only on its own database — the separate database
gives data isolation, the separate role name gives credential isolation, and you
need both.
:::

:::tip[Agency Tip]

When you stand up a new environment, the role exists the moment migrations
run, but Directus cannot connect until you set its password. Set it as part
of the same secret-provisioning step that fills `CERT_HMAC_*` and
`GOOGLE_CLIENT_SECRET` — and rotate it on the same cadence as your other
service credentials. A password set inside a migration would land in git;
keeping it out of band is the whole point of the no-password `CREATE ROLE`.

:::

## SQLite is a no-op here

`0008` returns early on any non-Postgres dialect — SQLite has no concept of
roles or grants. The local smoke suite runs against SQLite, so this
migration simply does nothing there. The isolation it provides is a
Postgres-only, production-only property, which is consistent with the
[Postgres-only stance](./postgres-only-features.md) for the whole schema.
