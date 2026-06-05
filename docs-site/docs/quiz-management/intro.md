---
id: intro
title: Quiz management
sidebar_position: 1
---

# Quiz management

> **Phase 0 stub.** Phase 5a expands this into the page set listed below.

## Scan box

- The quiz is one module of the v2 backend
  (`backend/app/modules/quiz/`). It owns generation, grading,
  certificate signing, certificate PDF rendering, email delivery and the
  admin question CRUD.
- **Real and dev certificates are visually distinguishable** in v2 — the
  current build issues identical PDFs from dev sessions, which is a
  governance bug. Phase 2c adds an `attempts.environment` column, a
  visible "DEV / NOT FOR ISSUANCE" watermark, and a separate signing key.
- **Already-issued real certificates keep verifying.** The HMAC input
  (`cert_id|email|score|submitted_at`) is unchanged; existing rows
  default to `environment='production'`.
- The question bank lives in Postgres (`questions`), seeded from
  `backend/data/question_bank.json`. UGC questions added through the feed
  carry `q.ugc.<feedid>` IDs.
- Quiz Admin and Platform Admin roles (staff-plane, via Directus) are the
  only writers of `questions` after launch. Learners never see admin
  surfaces.

## What lives here

This section is the quiz operator's manual: how to author and review
questions, what the quiz lifecycle looks like end-to-end, how
certificates are signed and verified, how dev mode now differs visibly
from real, and which admin flows live where.

Source contracts:
- `docs/architecture/v2/04-authz-model.md` — quiz admin permissions.
- Phase 2c (certificate dev-mode) in `v2-plan.md`.
- `docs/architecture/v2/07-security-baseline.md` — signing-key rotation
  via the new `signing_keys` table.

## Planned pages (Phase 5a)

1. **Question bank** — schema, authoring, versioning, the UGC sub-tree.
2. **Quiz lifecycle** — start → take → submit → grade → cert → email,
   with a Mermaid sequence diagram.
3. **Certificates** — signing, PDF render, verification URL,
   signing-key rotation.
4. **Dev mode vs real** — visible watermark, separate key, the
   `attempts.environment` column.
5. **Verification** — `/verify/{cert_id}` flow; what a stranger sees.
6. **Admin flows** — Quiz Admin and Platform Admin actions in Directus
   and via the FastAPI admin endpoints.

:::info Before / After

**Before (current):** a developer running `DEV_MODE=true` locally issues
a certificate that is byte-identical to a real one — same PDF, same
signature surface.

**After (v2, Phase 2c):** the same flow issues a PDF stamped
*"DEVELOPMENT — NOT FOR ISSUANCE"*, signed by a separate dev key, with
`attempts.environment='development'`. The verify page tells the visitor
the certificate is a dev artefact.

:::

## Cross-references

- `docs/architecture/v2/03-data-model.md` §2 — `attempts`,
  `signing_keys`, `quiz_sessions` tables.
- `docs/architecture/v2/04-authz-model.md` — Quiz Admin role permissions.
- `docs/architecture/v2/07-security-baseline.md` — certificate signing
  posture.
