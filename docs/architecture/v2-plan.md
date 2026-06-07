# DEPT® Anatomy of Code — v2 Re-architecture Plan

> Status: **Phase 0 in progress** · Branch: `v2` · Main stays live until cutover.
> This document is the shared contract. Every agent on the v2 effort reads it first.

## Why

A full audit (June 2026) found the folder names misrepresent the architecture:
`quiz-certification/` is not the quiz module — it is the **entire backend** (one
FastAPI app serving quiz + feed + course-content APIs + media + moderation +
admin). The front-end is a buildless ES-module app with three modes. Content is
triplicated (git-JSON ↔ frozen HTML monolith ↔ Postgres) with an ambiguous
source of truth. There is no CMS, no caching, no migration tool, two disconnected
role systems, dev certificates indistinguishable from real ones, and weak
hardcoded secret defaults.

This plan re-architects the system into a clean modular monolith with a real CMS,
proper authorization, environment management, caching, and documentation — without
losing existing content, data, or functionality.

## Locked decisions (from the planning gate)

| Decision | Choice | Implication |
|---|---|---|
| **Module architecture** | **Modular monolith** | ONE FastAPI backend internally split into `core/` (shared) + `modules/` (quiz, content, feed, media, cms). ONE buildless front-end. Single primary deploy unit + the Directus service. |
| **CMS** | **Directus over the existing Postgres** | Separate Node service. Provides the staff/editor plane: admin UI, RBAC for editors, asset management, REST/GraphQL, audit trail, webhooks. FastAPI stays the learner-facing runtime API. |
| **Front-end** | **Buildless ES modules, reorganised** | No bundler/framework. Reorganise into `core/`/`shared/`/`modules/`/`styles/`. Centralise config/theme/nav. Preserve byte-for-byte visual parity with the frozen monolith. |
| **Risk posture** | **Fork to `v2`** | All work on `v2`. `main` untouched and running. Parity verified at every gate. Cut over only when v2 is proven. |

## Target shape (high level — Blueprint agent finalises exact tree)

```
backend/                         # the modular monolith (was quiz-certification/)
  core/                          # shared: db, auth, config, encryption, security, cache
  modules/
    quiz/                        # routes, service, models, certificate, generator
    content/                     # course APIs, ETL, framework
    feed/                        # feed APIs, moderation
    media/                       # upload, streaming, large objects
    cms/                         # Directus integration seam (webhooks, read adapters)
  main.py                        # mounts per-module routers
  migrations/                    # Alembic
frontend/                        # buildless (was app/)
  core/                          # router, config, theme, api-client
  shared/                        # dom, blocks, render
  modules/
    course/                      # modes: manual, read
    feed/
    quiz/                        # link / embed
    resources/                   # runbook, checklist, faqs
  styles/                        # tokens, monolith[frozen], per-module
content/                         # consolidated source-of-truth (was content-architecture + content-system)
cms/                             # Directus project (config, schema snapshots, extensions)
infra/                           # deploy.sh, apache, systemd, env templates, start_local.sh
docs-site/                       # Docusaurus
docs/architecture/               # these design contracts
tests/baseline/                  # parity safety net
```

## Guiding principles

1. **Contracts before code.** Phase 0 produces the specs below. Later phases code against them.
2. **Parity is the acceptance test.** `tests/baseline/` captures current behaviour and is re-run at every phase gate to prove no loss of content or functionality.
3. **`v2` branch + disjoint file areas.** Parallel agents own non-overlapping paths. The restructure (Phase 1) is partitioned and integrated carefully.
4. **Phases are sequential; agents within a phase run in parallel.** Each phase ends in a gate.

## Phase plan

| Phase | Goal | Gate |
|---|---|---|
| **0 · Design & safety net** | Produce all design contracts + the parity harness + docs scaffold | **User approves the blueprint** |
| **1 · Restructure + clean code** | Execute the move into the v2 shape; delete dead code; fix all path references | Parity harness matches baseline |
| **2 · Backend hardening** | DB+migrations (2a) → then authZ (2b), cert dev-mode (2c), config/secrets (2d), app security (2e) in parallel | Tests + security review |
| **3 · Infra/env/perf/network** | Environment management (3a), caching/perf (3b), network/process security (3c) | Deploy dry-run + security review |
| **4 · Directus CMS + nav/IA** | Stand up Directus (4a), unified navigation + SSO-into-quiz (4b), live authoring + moderation (4c) | Editor + learner flows verified |
| **5 · Docs + cutover** | Docusaurus six sections (5a), final security review + parity + cutover plan (5b) | Ship |

## 12-item coverage

| # | Item | Lands in |
|---|---|---|
| 1 | Restructure / modular monolith / stalwart FE | Phase 0 design → Phase 1 |
| 2 | CMS for 4 content types (Directus) | Phase 0 map → Phase 4 |
| 3 | Environment management | Phase 0 → Phase 3a |
| 4 | Clean-code pass | Phase 1 |
| 5 | Performance / caching (Apache + Postgres) | Phase 0 → Phase 3b |
| 6 | Postgres schema + DB integration | Phase 0 → Phase 2a |
| 7 | Security (code/content/network/encryption/process) | Phases 0, 2e, 3c, 5b |
| 8 | SSO + authorization roles | Phase 0 → Phase 2b |
| 9 | Certificate dev-mode | Phase 2c |
| 10 | Docusaurus docs | Phase 0 scaffold → Phase 5a |
| 11 | Configurable values (Google/LLM keys) | Phase 0 → Phase 2d + Phase 4c |
| 12 | Navigation / IA / segregation | Phase 0, Phase 1, Phase 4b |

## Phase 0 deliverables (this phase)

| Doc | Owner agent | Covers |
|---|---|---|
| `v2/01-blueprint.md` | Blueprint | Exact v2 tree, module boundaries, router-mount scheme, file-by-file migration map, path-reference migration map — items 1, 12 |
| `tests/baseline/` + `v2/02-parity-method.md` | Baseline/parity | Route inventory, content checksums, DB snapshot, smoke script, parity method — the safety net |
| `v2/03-data-model.md` | Data model | Target Postgres schema, Alembic plan, Directus-compat, source-of-truth resolution — item 6 |
| `v2/04-authz-model.md` | AuthZ model | Role taxonomy, permission matrix, persona-as-profile, SSO+PKCE, Directus auth coexistence — item 8 |
| `v2/05-config-cms.md` | Config/CMS | Config & secrets registry, Google+LLM key design, Directus collection map — items 2, 11, 3 |
| `v2/06-caching-performance.md` | Caching/perf | Apache cache/deflate/expires/HTTP2, cache-busting, app/Redis cache, Postgres tuning — item 5 |
| `v2/07-security-baseline.md` | Security baseline | Full security checklist mapping each finding → remediation → phase — item 7 |
| `docs-site/` | Docs scaffold | Docusaurus structure + section stubs — item 10 |

## Open decisions to confirm at the Phase 0 gate

Design agents propose a **default** with the alternative + tradeoff so these can be flipped:

1. **Role taxonomy.** Proposed default — learner-plane (Google SSO): `Learner`, `Feed Contributor`; staff-plane (Directus): `Content Author`, `Quiz Admin`, `Feed Moderator`, `Platform Admin`. The old `pm/ba/architect` personas become a **profile attribute** (drives quiz-difficulty recommendation), not an authZ role.
2. **Course source-of-truth under Directus.** Proposed default — Postgres becomes the editable source; git-JSON becomes an export/seed (shift from current ADR 0001).
3. **Media strategy.** Proposed default — keep the Postgres large-object pipeline for runtime range-streaming; use Directus for asset management/metadata.

## Hard constraints (do not violate)

- **No loss of content or functionality.** Parity harness must pass at each gate.
- **Already-issued real certificates must keep verifying.** Cert dev-mode work must be backward-compatible.
- **Brand/voice rules in `CLAUDE.md` still apply** to all content and UI copy.
- **Visual parity** of the course against the frozen monolith (`content-system/anatomy-of-code-course.html`).
- **`main` is never edited** during the v2 effort.
