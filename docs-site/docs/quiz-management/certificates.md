---
id: certificates
title: Certificates
sidebar_position: 4
---

# Certificates

A pass mints a credential DEPT® puts its name on. The certificate system has
three jobs: render a branded PDF, seal it with an HMAC that proves it was
issued by us, and make a development certificate impossible to mistake for a
real one. This page covers all three, plus the guarantee that anchors the
whole design — every certificate ever issued in production keeps verifying.

## Scan box

- **The PDF is rendered, not stored.** `certificate.py` draws a landscape
  ReportLab PDF on demand from the persisted attempt. There is no static PDF
  archive to keep in sync.
- **The seal is an HMAC, not a key inside the PDF.** Each attempt carries an
  HMAC-SHA256 over `cert_id|email|score|submitted_at` in the `attempts.signature`
  column. The PDF holds the human-readable cert ID; the proof lives in the
  database.
- **Keys are per-environment and live in env vars.** The `signing_keys` table
  names *which* env var holds the secret; the bytes never touch the database.
  A development cert is signed by a different key from production.
- **The environment is visible.** Non-production certs get a `DEV-` or `STG-`
  cert-ID prefix and a diagonal watermark. Production certs are byte-stable
  and unmarked.
- **No certificate ever silently breaks.** The HMAC formula is unchanged from
  v1, the production prefix is unchanged, and existing rows default to
  `environment='production'`. The canary `CCA-F-20260605-E79E74AB` proves it
  on every smoke run.

## Anatomy of a certificate

A certificate is not one artefact — it is three coordinated things:

```text
  ┌─────────────────────────────────────────────────────────────┐
  │  attempts row (Postgres)                                     │
  │    cert_id          CCA-F-20260605-E79E74AB                  │
  │    signature        <HMAC-SHA256 hex>      ← the proof       │
  │    environment      production                              │
  │    signing_key_id   → signing_keys.id      ← which key      │
  │    score, submitted_at, user_email         ← HMAC inputs    │
  └─────────────────────────────────────────────────────────────┘
                │                          │
                ▼                          ▼
  ┌───────────────────────┐    ┌───────────────────────────────┐
  │  PDF (certificate.py) │    │  Verifier (/verify/{cert_id}) │
  │  rendered on demand   │    │  recomputes the HMAC, compares│
  │  from the row         │    │  against the stored signature │
  └───────────────────────┘    └───────────────────────────────┘
```

The PDF is a *view* of the attempt. The signature is the *fact*. Losing or
regenerating a PDF costs nothing; the credential is the signed row.

## The PDF — ReportLab, DEPT®-branded

`certificate.generate(record)` draws a landscape A4 PDF with the DEPT® brand
language: ochre `#FF4900` accents, the `DEPT®` brand mark, a serif name, a
mono detail row. It needs only `cert_id`, the user's name and email, `score`,
`difficulty` and `submitted_at` — all of which live on the attempt — so it
can be regenerated at any time.

That regenerate-on-demand property is why `GET /certificate/{cert_id}`
(`routes.py`) can rebuild a missing PDF from the stored attempt rather than
404. The owner of the certificate (matched by session email) always gets a
fresh, correct PDF.

The PDF footer points the reader at `dept.academy/verify/{cert_id}` — verify
by ID, no login required. The proof of authenticity is not in the file; it is
the verifier recomputing the HMAC against the database.

## The HMAC seal

The signature is an HMAC-SHA256 over a fixed formula
(`verification.hmac_score_payload`):

```text
  HMAC( key, "cert_id|email_lower|score:.6f|submitted_at" )
```

Two design choices in that one line carry the whole no-loss guarantee:

- **The formula is frozen.** It is byte-identical to the v1 formula. Changing
  the order of fields, the case of the email, or the float formatting would
  break every certificate ever issued. It does not change.
- **`score` is a fraction, hashed to six decimal places.** The attempt stores
  `score` as a 0–1 fraction in a `DOUBLE PRECISION` column precisely so the
  value that goes into `f"{score:.6f}"` round-trips exactly. A percentage
  column would have rounded, and rounding would have changed the hash.

The HMAC is computed at issue time in `storage.save_attempt` and stored in
`attempts.signature`. Verification recomputes it and compares with
`hmac.compare_digest` — a constant-time comparison, so a near-miss signature
leaks no timing information.

## The keys — per-environment, never in the database

The secret bytes live in environment variables. The `signing_keys` table
holds only metadata — which key, for which environment, named by which env
var, and whether it may still verify.

| Row (`name`) | Environment | Env var read for material | Seeded by |
| --- | --- | --- | --- |
| `legacy-prod` | `production` | `CERT_HMAC_LEGACY` | migration `0005` |
| `dev-default` | `development` | `CERT_HMAC_DEV` | migration `0007` |
| `stg-default` | `staging` | `CERT_HMAC_STG` | migration `0007` |

At sign and verify time, `verification.load_key_material` reads
`os.getenv(env_var_name)`. If the variable is unset or empty, it raises — the
code **never** silently falls back to `SECRET_KEY`. That silent fallback was
the original vulnerability (catalogued as F-CER-01 in `07-security-baseline.md`):
dev and prod sharing one key. The fix is structural — the secret is resolved
through the table, and a missing secret is a hard failure, not a downgrade.

:::note[Why This Matters]
Decoupling the cert key from `SECRET_KEY` means the two rotate independently.
Rotating `SECRET_KEY` invalidates active login sessions — a routine
operation. Before this change, that same rotation would have silently broken
every issued certificate, because the certs were signed with `SECRET_KEY`.
Now the cert HMAC reads `CERT_HMAC_LEGACY`, which is left untouched, so
sessions and credentials have separate lifetimes.
:::

## The cert-ID prefix policy

The cert ID encodes its environment in its prefix
(`verification.apply_env_prefix`):

| Environment | Prefix | Example |
| --- | --- | --- |
| `production` | none | `CCA-F-20260605-E79E74AB` |
| `staging` | `STG-` | `STG-CCA-F-20260605-XXXXXXXX` |
| `development` | `DEV-` | `DEV-CCA-F-20260605-XXXXXXXX` |

Production keeps the bare `CCA-F-` prefix **forever** — every URL ever printed
on a real certificate must keep resolving. The prefix is applied in
`save_attempt` *before* signing, because the prefixed `cert_id` is part of the
HMAC input. `apply_env_prefix` is idempotent and only ever stamps a
production-format ID, so re-saving a row never double-stamps or mutates a
legacy cert.

## The development watermark

Outside production, the PDF carries a diagonal ochre watermark and a
clarifying footer line (`certificate.py`):

| Environment | Watermark | Footer |
| --- | --- | --- |
| `development` | `DEVELOPMENT — NOT VALID FOR CREDENTIALS` | "…development environment. Not a credential." |
| `staging` | `STAGING — TEST CERTIFICATE` | "…staging environment. Test certificate." |
| `production` | none | standard authenticate-by-ID line |

The watermark is drawn first, behind the rest of the layout, in ochre
`#FF4900` at 0.22 opacity — the same tint scrim the course HTML uses for
blockquote backgrounds, so the brand reads the same in print and on screen.
Crucially, the production branch is `None`: `certificate.generate` skips the
watermark code path entirely for a production cert, so production output is
byte-stable relative to the pre-dev-mode build.

:::info[Before / After]

**Before:** a developer running `DEV_MODE=true` could issue a certificate that
was byte-identical to a real one — same PDF, same prefix, signed with the same
key the public verifier validated against. A casual reader, and the verifier
itself, could not tell a dev artefact from a credential.

**After:** the same flow issues a PDF stamped *DEVELOPMENT — NOT VALID FOR
CREDENTIALS*, with a `DEV-CCA-F-…` ID, signed by `dev-default` against
`CERT_HMAC_DEV`, and `attempts.environment='development'`. The verifier reads
the environment off the row and badges it. A dev cert cannot pass as real to a
human or to the verifier.

:::

## The no-data-loss guarantee

This is the hard constraint the entire design protects: **every certificate
ever issued in production must keep verifying, byte for byte, after every
change in this module.** Three facts make that true:

1. The HMAC formula is unchanged from v1.
2. The production cert-ID prefix is unchanged (bare `CCA-F-`).
3. Existing attempt rows default to `environment='production'` and are
   backfilled to the `legacy-prod` key, whose material is the original
   `SECRET_KEY` value seeded into `CERT_HMAC_LEGACY` at cutover.

The proof is a canary. `CCA-F-20260605-E79E74AB` is a real production
certificate, and the baseline smoke suite asserts
`GET /verify/CCA-F-20260605-E79E74AB → valid=true` on every run (strict mode,
`SMOKE_REAL_CERT_CHECK=1`). It has held green from Phase 2 through the final
v2 cut — the certificate that existed before any of this work still verifies
as valid.

:::warning[Common Pitfall]
The one operator step that must not be skipped: before the production cutover,
set `CERT_HMAC_LEGACY` to the exact current value of `SECRET_KEY` and reload
the service. The `legacy-prod` row points every historical certificate at this
env var. If it is unset, `load_key_material` raises and *no* production
certificate verifies — the canary goes red immediately. This is a one-line
`.env` step, documented in the runbook, and it is the difference between a
clean cutover and a credential outage.
:::

## What the verifier does with all this

The verifier recomputes the HMAC, but it also reasons about the key's state —
is it retired, has it expired? That logic, and exactly what a stranger sees
when they check an ID, is on the [Verification](./verification) page.
