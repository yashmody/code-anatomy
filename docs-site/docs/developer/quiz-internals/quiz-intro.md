---
id: quiz-intro
title: Quiz management
sidebar_position: 1
---

# Quiz management

The quiz is one module of the v2 backend — `backend/app/modules/quiz/`. It
owns the certification exam end to end: question sampling, server-side
grading, the pass mark, the signed PDF certificate, the public verifier, and
the admin surfaces that staff use to curate the bank. This section is the
operator's manual for all of it.

## Scan box

- **The quiz is the certification gate.** A learner starts an exam, the
  server samples 30 questions, grades the submission server-side, and a pass
  (25 of 30 correct) mints a signed certificate. The client never sees a
  correct answer until it submits.
- **Grading and answer custody are server-only.** Correct indices live in the
  server's quiz state, never in the payload the browser holds. The browser
  posts back only the learner's chosen indices. This is the whole anti-cheat
  story.
- **Certificates are HMAC-sealed per environment.** Each certificate carries
  an HMAC over `cert_id|email|score|submitted_at`, signed with the
  environment's key from the `signing_keys` table. A development certificate
  cannot verify against the production key, and vice versa.
- **Real certificates never break.** The HMAC formula is unchanged from v1, so
  every certificate ever issued in production keeps verifying. The canary
  `CCA-F-20260605-E79E74AB` is asserted `valid=true` in the smoke suite on
  every run.
- **The bank is Postgres, and only staff write to it.** Questions live in the
  `questions` table. Learners can *propose* questions through a feed scenario,
  but those land as `pending_review` and a moderator must approve them before
  they reach the quiz pool.

## What lives here

The quiz module is small in line count and dense in consequence. It is the
one place in the platform where a learner earns a credential that DEPT® puts
its name on, so the rules around scoring, signing, and verification are
deliberately tight. The module also carries one piece of legacy state — an
in-process dictionary of active quizzes — that pins the application to a
single worker until it is moved into Postgres.

This section walks the module in the order a learner experiences it, then
turns to the staff side. Read the lifecycle page first; everything else
(the bank, the certificate, the verifier, the admin surfaces) hangs off the
two moments in that lifecycle where the server takes custody of an answer.

## Section map

import DocCardList from '@theme/DocCardList';

<DocCardList />

The pages, in reading order:

1. **Quiz lifecycle** — start → server-side generation (no-repeat) → take →
   submit → server-side grading → pass mark → certificate. The spine of the
   module, with the full request sequence.
2. **The question bank** — the `questions` schema, authoring through the
   admin endpoint, in-place versioning, and the user-generated-content path
   where a feed scenario becomes a `pending_review` question.
3. **Certificates** — the ReportLab PDF, HMAC signing via `signing_keys`,
   the `CCA-F-` / `DEV-` / `STG-` cert-ID prefixes, the development
   watermark, and the no-data-loss guarantee.
4. **Verification** — the public `/verify/{cert_id}` flow, the structured
   verifier result, key rotation and expiry, and exactly what a stranger
   sees.
5. **RBAC and admin** — the quiz admin's permissions, the moderation queue
   for user-submitted questions, the admin endpoints, and the cooldown and
   multi-worker caveats an operator must know.

## Source contracts

Everything in this section is grounded in the shipped v2 code and the design
contracts that produced it:

- `backend/app/modules/quiz/` — `service.py` (generation + grading),
  `routes.py` (the runtime endpoints), `storage.py` (persistence + the
  signing wrappers), `verification.py` (HMAC sign/verify + rotation),
  `certificate.py` (the PDF), `email.py` (delivery).
- `backend/app/core/deps.py` — the locked permission matrix that authorises
  every admin route.
- `docs/architecture/v2/02-parity-method.md` — the no-loss method and the
  real-cert canary.
- `docs/architecture/v2/03-data-model.md` — the `attempts`, `questions`,
  `signing_keys` and `quiz_sessions` tables.
- `docs/architecture/v2/04-authz-model.md` — the quiz admin role and its
  permissions.
- `docs/architecture/v2/07-security-baseline.md` §8 — the certificate
  dev-mode design.
