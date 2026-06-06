# DBA handover — dev Postgres hardening + Directus dev role

**Target:** the shared instance `20.228.243.225:5432`, database **`codecoder-dev`**
(PostgreSQL 14.23). App role **`ccdev`** is already the owner of `codecoder-dev`
and owns its 14 application tables.

**What is already done (no DBA action needed):**

- `codecoder-dev` schema is built and seeded (Alembic at `0007`, 500 questions,
  course content, feed, users, attempts, one 48 MB media large object).
- Extensions `hstore` + `pgcrypto` are installed in `codecoder-dev` (created by
  `ccdev` as owner — they are trusted in PG 13+).

**What we need from you — three items.** A, B, C below.

> ⚠️ **Coordination — items A2 and A3 will break the running app until we update
> our config.** The app currently connects as `ccdev` with **no password over a
> cleartext (non-TLS)** link (`sslmode=disable`). The moment you set a `ccdev`
> password or require TLS, our connection fails until we update `backend/.env`.
> So: **do A1/B/C first; schedule A2/A3 together and send us the `ccdev`
> password at the same time** — we will switch `backend/.env` to
> `ccdev:<password>@…?sslmode=require` and re-verify immediately.

---

## A · Security hardening (the important asks)

### A1 — confirm `directus_app_dev` is granted on `codecoder-dev` ONLY
Roles are cluster-global but GRANTs are per-database. The dev Directus role must
never be granted on the prod database (`codecoder`/`coder-prod`), so a dev
credential cannot reach prod. (Role + grants are created in section B.)

### A2 — set passwords (currently `ccdev` has none)
```sql
-- ensure scram (PG14 default; confirm)
SHOW password_encryption;          -- expect scram-sha-256
ALTER ROLE ccdev            WITH PASSWORD '<STRONG_CCDEV_PASSWORD>';
ALTER ROLE directus_app_dev WITH PASSWORD '<STRONG_DIRECTUS_DEV_PASSWORD>';
```
Send both passwords back to us (out of band) so we can update our git-ignored
`.env` files.

### A3 — enable TLS + tighten `pg_hba.conf`
The server currently advertises **no SSL** and uses **trust** auth for these
hosts. Please:

1. `postgresql.conf`: `ssl = on` with a cert/key (internal CA or Let's Encrypt),
   then `SELECT pg_reload_conf();`
2. `pg_hba.conf`: replace the broad `trust` rules for these DBs with
   `scram-sha-256` over `hostssl`, restricted to the app/CMS host IP(s):
   ```
   # TYPE   DATABASE       USER              ADDRESS              METHOD
   hostssl  codecoder-dev  ccdev             <app_host_ip>/32     scram-sha-256
   hostssl  codecoder-dev  directus_app_dev  <cms_host_ip>/32     scram-sha-256
   ```
   Remove/avoid any `host … codecoder-dev … trust` and any `0.0.0.0/0` rules for
   these roles. Then `SELECT pg_reload_conf();`

---

## B · Directus dev role + table isolation

Run as a superuser, connected to **`codecoder-dev`**. This mirrors our Alembic
migration `0008` with `DIRECTUS_DB_ROLE=directus_app_dev`. The GRANT/REVOKE
statements act on tables owned by `ccdev`, so a superuser (or `ccdev` itself)
must issue them.

```sql
\c codecoder-dev

-- 1. login role (password set in A2)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'directus_app_dev') THEN
    CREATE ROLE directus_app_dev LOGIN;
  END IF;
END $$;

-- 2. schema: Directus creates + manages its own directus_* tables here
GRANT CREATE, USAGE ON SCHEMA public TO directus_app_dev;

-- 3. scoped grants (exactly the collections Directus edits/reads)
GRANT SELECT                         ON users, roles, user_roles      TO directus_app_dev;
GRANT SELECT, INSERT, UPDATE, DELETE ON course_chapters, questions    TO directus_app_dev;
GRANT SELECT, INSERT, UPDATE         ON frameworks                    TO directus_app_dev;  -- no DELETE
GRANT SELECT, UPDATE                 ON feed_items                    TO directus_app_dev;  -- moderation only
GRANT SELECT, INSERT, UPDATE         ON app_config                    TO directus_app_dev;  -- no DELETE
GRANT SELECT                         ON media_assets                  TO directus_app_dev;  -- metadata only
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public                 TO directus_app_dev;

-- 4. HARD denial of runtime + audit tables (never editor-reachable)
REVOKE ALL ON attempts, quiz_sessions, signing_keys, auth_audit       FROM directus_app_dev;
```

We will `alembic stamp 0008_directus_app_role` on our side afterwards so the
migration history matches — you do not need Alembic.

---

## C · Verification (please run + return the output)

```sql
-- roles exist and can log in
SELECT rolname, rolcanlogin FROM pg_roles
WHERE rolname IN ('ccdev','directus_app_dev');

-- isolation: denied tables -> f, allowed -> t
SELECT
  has_table_privilege('directus_app_dev','attempts','SELECT')        AS attempts_select_should_be_f,
  has_table_privilege('directus_app_dev','signing_keys','SELECT')    AS signing_keys_select_should_be_f,
  has_table_privilege('directus_app_dev','auth_audit','SELECT')      AS auth_audit_select_should_be_f,
  has_table_privilege('directus_app_dev','course_chapters','SELECT') AS chapters_select_should_be_t,
  has_table_privilege('directus_app_dev','questions','INSERT')       AS questions_insert_should_be_t,
  has_table_privilege('directus_app_dev','feed_items','UPDATE')      AS feed_update_should_be_t;
```

TLS check (after A3), from a host that is allowed in `pg_hba`:
```bash
psql "host=20.228.243.225 dbname=codecoder-dev user=ccdev sslmode=require" \
  -c "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid();"
```

---

## Summary of what changes on our side once you're done

| You do | We do |
|---|---|
| A2 set `ccdev` password | update `backend/.env` → `ccdev:<pw>@…` |
| A3 enable TLS | flip `sslmode=disable` → `sslmode=require` in `backend/.env` |
| B create `directus_app_dev` (+ A2 password) | point `cms/.env` at the remote, boot Directus, `alembic stamp 0008` |
| C return verification output | confirm app + Directus + isolation green end-to-end |
