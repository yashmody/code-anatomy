# v2/phase-5 — Final report (the capstone)

> Status: **Phase 5 SEALED · v2 effort COMPLETE pending user review.** Branch
> `v2`. `main` untouched. Phases 0–4b sealed; Phase 5 (docs + final security
> review + parity + cutover plan) delivered.
> Owner: Phase 5 orchestrator. Audience: the user (architect) deciding GO /
> NO-GO on promoting v2.

This is the last document in the v2 re-architecture. It states what the whole
effort delivered, closes out the 12-item plan, carries the final security
verdict and parity result verbatim, and gives a single cutover-readiness call
with the conditions spelled out. It does not re-explain the architecture — the
six docs-site sections and the eight Phase 0 contracts do that. It is the
decision page.

---

## 0 · Scan box

- **What:** the capstone for v2 — six documentation sections built and building
  green, a full code-level security review, a full parity + performance
  re-validation, and a written cutover plan.
- **Why:** v2 re-shaped the platform into a two-plane modular monolith (FastAPI
  app plane + Directus editorial plane over one Postgres) with media in Postgres
  large objects, server-side authorisation, and per-environment certificate
  signing. Phase 5 proves it is documented, safe, and parity-clean before it
  ships.
- **So what:** the readiness call is **GO-WITH-CONDITIONS**. The credential /
  authorisation / secret controls are implemented and verified; parity is green
  (smoke 15/15, imports 98/98, content byte-identical, Alembic `0008`,
  `directus_app` isolation intact); the conditions are **two MUST-FIX security
  items** before traffic opens, plus the CSP enforce flip on a soak timeline.
- **Honest residue:** zero CRITICAL / zero HIGH security findings remain open;
  six MEDIUM, four LOW, three INFO are documented below — none forge a
  credential, bypass authz, or leak a secret. Item 4c (relational decomposition)
  is **deferred by design**, not failed — authoring works today via Directus
  over the JSON-backed schema.

---

## 1 · The v2 effort at a glance

v2 was run as a **gated, parallel-agent workflow**: Phase 0 produced eight
design contracts (`01`–`08`) plus a parity safety net under `tests/baseline/`;
each later phase coded against those contracts, ran agents in parallel over
disjoint file areas, and ended in a gate where parity was re-run to prove no loss
of content or functionality. `main` was never touched; everything lives on `v2`.

```
┌─ v2 PHASES (0 → 5) ─────────────────────────────────────────────────────────┐
│ 0  Contracts + parity net + Docusaurus scaffold ............... SEALED       │
│ 1  Restructure → modular monolith + buildless FE .............. SEALED       │
│ 2  Postgres schema / Alembic / SSO+authz / cert dev-mode /                   │
│    config registry / security pass (2a–2e) ................... SEALED       │
│ 3  Environment management + Apache/Postgres perf + security ... SEALED       │
│ 4a Directus stand-up over the shared Postgres ................. SEALED       │
│ 4b Unified navigation + SSO-into-quiz + moderation ............ SEALED       │
│ 4c Live authoring / relational decomposition ................. DEFERRED     │
│ 5  Docs (6 sections) + security review + parity + cutover ..... THIS REPORT │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Final architecture (the state this report certifies):** a modular-monolith
FastAPI app (`backend/app/{core,modules}`) is the application plane — quiz,
certificate sign/verify, learner Google SSO, the cache-backed runtime read API.
Directus 11 (`cms/`) is the editorial content + config **write** plane over the
**same** `codecoder` Postgres, connecting as the scoped `directus_app` role. The
front-end is a buildless ES-module SPA (`frontend/`). All media lives in Postgres
large objects and is streamed by FastAPI `/media/{video,image}/{asset_id}` with
HTTP Range — **no S3, no object store, no filesystem media store.** Roles split
two planes: learner-plane (Google SSO) `learner` + `feed_contributor`;
staff-plane (Directus) `content_author`, `quiz_admin`, `feed_moderator`,
`platform_admin`. `require_permission` enforces server-side; `/auth/me` exposes
roles + permissions.

---

## 2 · 12-item closure matrix

Every item from the v2 plan's 12-item coverage table, where it was addressed,
and its status. **Eleven DONE, one DEFERRED.**

| # | Item | Addressed in | Status |
|---|------|--------------|--------|
| 1 | Restructure / modular monolith / buildless FE | Phase 1 — `backend/app/{core,modules}` + buildless `frontend/` | **DONE** |
| 2 | CMS for the 4 content types (Directus) | Phase 4a — Directus over shared Postgres, introspect-not-own | **DONE** |
| 3 | Environment management | Phase 3a — `APP_ENV`, fail-closed `validate_for_env()`, `.env.*.example` templates | **DONE** |
| 4 | Clean-code pass | Phase 1 — module boundaries, composition root, per-module file convention | **DONE** |
| 5 | Performance / caching (Apache + Postgres) | Phase 3b — `AppCache` memory\|redis, Apache cache/deflate/HTTP2, Postgres pooling | **DONE** |
| 6 | Postgres schema + DB integration | Phase 2a — Alembic `0001`→`0008` (head `0008`), 13 app tables | **DONE** |
| 7 | Security (code/content/network/encryption/process) | Phases 0, 2e, 3c, **5b** — see §4. Original CRITICALs all closed | **DONE** (residual MED/LOW open) |
| 8 | SSO + authorisation roles | Phase 2b — Google SSO + PKCE, `PERMISSION_GRANTS`, `require_permission` | **DONE** |
| 9 | Certificate dev-mode | Phase 2c — per-environment `signing_keys`, `DEV-`/`STG-` prefixes + watermark, prod byte-stable | **DONE** |
| 10 | Docusaurus docs | Phase 0 scaffold → **Phase 5a** — six sections, 42 pages, build green | **DONE** |
| 11 | Configurable values (Google/LLM keys) | Phase 2d — three-tier config, `app_config` registry, `cms_client` fallback | **DONE** |
| 12 | Navigation / IA / segregation | Phases 0/1/4b — hash router, Manual/Read/Feed, role-gated moderation | **DONE** |

### 2.1 The one deferral — item-2/11 tail: 4c relational decomposition

4c was planned to decompose the JSON-backed course/config schema into fully
relational Directus collections (the "live authoring" tail of items 2 and 11).
It is **deferred, not failed**: authoring works **today** — `content_author`
edits content via Directus over the existing schema, the loopback webhook
invalidates the cache, and the read path stays on FastAPI. The relational
decomposition is an editor-ergonomics upgrade, not a correctness gap. It carries
no parity or security debt. Tracked as the single optional follow-on in §7.

---

## 3 · Documentation (item 10) — DONE

### 3.1 Build result

`npm run build` **exits 0** under **node@22** (Node v22.22.3) — system Node 25 is
broken on the box and CI/deploy must pin Node 22. Result:

- **42 HTML pages** across six sections + a real landing page.
- **31 Mermaid diagrams** render as SVG; ASCII `arch-diagram` blocks and the
  four-type admonitions render correctly.
- Local search index built (`@easyops-cn/docusaurus-search-local`).
- **Zero broken links, zero warnings, zero errors** — `onBrokenLinks: 'throw'`
  passes.

Two **environmental** build blockers were found and fixed by upgrading the
Docusaurus stack 3.5.2 → 3.10.1 (a webpackbar/ProgressPlugin schema crash and a
Mermaid SSG `useColorMode` crash, both known 3.5.x issues, neither a content
problem). The lockfile is committed for reproducibility. `node_modules`/`build`/
`.docusaurus` are gitignored and not tracked.

### 3.2 The six sections

System architecture, Front-end, Content architecture, Database, Quiz management,
Deployment — each with a LAYER-pattern landing page (Scan Box → declarative
prose → woven diagrams + callouts), authored against the real code and config,
not the aspirational design. Each section explicitly documents the **FINAL** v2
state: Postgres-large-object media (S3 negated everywhere), Directus as the write
plane (never the read path), Alembic head `0008`, and 4c as deferred.

### 3.3 Content-quality verdict — PASS

The read-only content-quality review of all 42 pages returned **PASS (with two
MED fixes worth making)**. Brand exact (the only hex anywhere is `#FF4900`),
Indian English throughout, zero AI-tells, LAYER discipline on every page, only
the four sanctioned callout types, accessibility clean (no skipped headings, no
bare link text, no raster images). The two MED items are cross-section
*consistency* fixes (a quiz-section admonition keyword mismatch and a
`CACHE_BACKEND=redis` vs `REDIS_URL` wording slip in two deployment pages),
neither blocking the build. They are documentation polish, not correctness or
security issues.

---

## 4 · Security review (item 7) — verdict + findings

The Phase 5b audit verified **every control in code/config**, not from the design
doc, across the entire v2 surface (`backend/app/`, `deploy.sh`, `cms/`,
`frontend/`, migrations, env templates).

### 4.1 Verdict

**GO for cutover — with 2 MUST-FIX items first.** The v2 security baseline is
substantially implemented and sound. The four original CRITICAL findings from
`07-security-baseline.md` — F-SEC-01/02 (in-source secret defaults), F-AUT-01/02
(dev auto-elevation), F-CER-01 (cross-env cert forgery) — are **all confirmed
closed in code**. No CRITICAL or HIGH issue remains open that would forge a
credential, bypass authz, or leak a secret.

**Severity counts:** CRITICAL 0 · HIGH 0 · MEDIUM 6 · LOW 4 · INFO 3.

### 4.2 Confirmed-sound controls (verified in code)

Secrets-in-git (only `*.env.example` tracked; real `.env` gitignored, blank in
prod/staging templates); fail-closed startup (`validate_for_env` refuses boot on
dev-default secrets in non-dev; the `KEEP_DEV_SECRET` escape hatch is not preset
anywhere); hardened session/cookies + PKCE pre-auth cookie; authz enforcement
(every privileged route carries `require_permission`, `platform_admin` the single
bypass, `/auth/me` returns only the caller's own roles); **Directus DB
isolation** (`0008` REVOKEs ALL on `attempts`/`quiz_sessions`/`signing_keys`/
`auth_audit` from `directus_app`); per-environment certificate HMAC with
`hmac.compare_digest`, prod path byte-stable, cross-env forgery blocked;
TLS/HSTS/CSP + app-side security headers; the dual-guarded webhook loopback
(Apache `Require ip` + app-side check); file-upload SVG/XML/HTML deny at two
layers + size cap + Pillow/ffprobe validation; Google SSO with S256 PKCE +
verified id_token + fail-closed domain enforcement; AES-256-GCM with fresh
per-call nonce; ORM/bound-parameter DB access (no SQL injection surface) with
SPA `esc()` on every user field; hardened systemd sandbox on both units.

### 4.3 Open findings (honest list)

| ID | Sev | Area | Gap (one line) |
|---|---|---|---|
| V2-F-01 | MEDIUM | CSP | CSP ships **Report-Only by default**; not enforcing until `CSP_ENFORCE=1` after soak. |
| V2-F-02 | MEDIUM | CSP | `Report-To` points at `/csp/report`, which **has no handler** — violation reports 404 and are lost. |
| V2-F-03 | MEDIUM | supply-chain | `fastapi` and `uvicorn[standard]` are **completely unpinned** in `requirements.txt`. |
| V2-F-04 | MEDIUM | supply-chain | **No SRI** on CDN scripts; mermaid pinned only to the floating `@11` tag. |
| V2-F-05 | MEDIUM | audit | Moderator approve/flag/remove actions **write no `auth_audit` row** (role grants + logins are audited). |
| V2-F-06 | MEDIUM | upload/DoS | Upload has a bandwidth throttle but **no per-user request-rate limit**; MIME sniff is offset-0 only. |
| V2-F-07 | LOW | config | `--forwarded-allow-ips='*'` makes `request.client.host` attacker-controllable; only Apache's `Require ip` saves the webhook. |
| V2-F-08 | LOW | upload | Large-object stream read-error path uses a bare `print` and yields a truncated body. |
| V2-F-09 | LOW | moderation | Auto-flag at `flag_count >= 1` — one user can flag-hide any post (griefing/availability). |
| V2-F-10 | LOW | secrets | Dev `.env` templates carry the literal dev markers (harmless; `validate_for_env` rejects them in non-dev). |
| V2-F-11 | INFO | naming | Permission-string drift (code `question.write` vs doc `question.publish`); no security impact. |
| V2-F-12 | INFO | cookies | `/logout` is still a GET (SameSite=Lax blocks the real CSRF; forced-logout is a minor nuisance, accepted). |
| V2-F-13 | INFO | cert | Printed cert date is render-time, not issuance-time; cosmetic — HMAC is over the stored `submitted_at`. |

### 4.4 MUST-FIX-BEFORE-CUTOVER (carried verbatim from the security review)

1. **V2-F-02 — wire (or remove) `/csp/report`.** Right now the `Report-To`
   header dangles at a 404. Either ship the endpoint or strip the directive;
   otherwise the Report-Only soak (which V2-F-01 depends on) collects zero data.
2. **V2-F-03 — pin `fastapi` and `uvicorn[standard]`.** Two completely-unpinned,
   security-load-bearing packages on a production box is the one supply-chain
   exposure that is trivial to close and genuinely risky to leave (a `pip
   install` on the next deploy can silently change proxy-header/middleware
   behaviour).

**Strongly recommended in the same window (not strict blockers):** V2-F-01
(enforce CSP after soak), V2-F-05 (audit moderator actions), V2-F-04 (SRI +
exact mermaid pin), V2-F-07 (narrow `--forwarded-allow-ips`).

---

## 5 · Parity + performance (item 5 + the safety net) — GREEN

The Phase 5b read-only parity + perf validation re-ran the full baseline. **Every
check PASS.**

| Check | Result |
|---|---|
| `smoke.sh` | **15/15 PASS** (re-run at close) |
| Cert canary `CCA-F-20260605-E79E74AB` strict verify | **PASS** — `valid=true (strict)` |
| `check-frontend-imports.py` | **PASS** — 98/98 relative imports resolve |
| Content parity (course JSON + feed + schemas) | **PASS** — byte-identical to main |
| Content parity (frozen monolith) | **PASS** — one intentional, non-content delta (20 bytes: a provenance comment + 3 resource-link repoints from the v2 restructure) |
| `alembic current` / `upgrade head` | **PASS** — `0008_directus_app_role (head)`, idempotent no-op |
| `AppCache` memory backend | **PASS** — caches + invalidates as specified |
| Live security headers | **PASS** — nosniff, `X-Frame-Options: DENY`, Referrer-Policy, Permissions-Policy, COOP, CORP, `x-request-id` |
| `/healthz` + `/readyz` (unauth) | **PASS** — 200 / `{db:ok}` |
| `directus_app` isolation | **PASS** — the 4 runtime/audit tables hard-denied; content readable |

The v2 content manifest is a strict **superset** of the Phase 0 baseline — zero
baseline lines missing or modified; the only additions are the `content/frozen/*`
resource pages the baseline did not enumerate. Content sha256s are preserved
across the tree rename. **No parity gap.**

---

## 6 · Cutover readiness

### **GO-WITH-CONDITIONS.**

The headline credential / authorisation / secret controls are implemented and
verified; parity is green across smoke, imports, content, schema, and Directus
isolation; the documentation builds clean and reads PASS. v2 is **safe to
promote once the conditions below are met.**

**Conditions (gate on these before opening traffic):**

1. **Land the two MUST-FIX security items** — V2-F-02 (`/csp/report` endpoint or
   drop the directive) and V2-F-03 (pin `fastapi` + `uvicorn[standard]`).
2. **Run the cutover plan's pre-flight + traffic gates** — every box in
   `cutover-plan.md` §1.7 and §3, with the cert canary verifying both
   pre-cutover (baseline) and post-cutover (acceptance).
3. **Pin Node 22 on the VM** — system Node 25 is broken; Directus needs a
   supported LTS, and the docs build is green only on node@22.

No parity gap blocks the GO. The deferral of 4c is not a condition — authoring
works today.

---

## 7 · What remains after v2

| Item | Type | Note |
|---|---|---|
| 4c — relational decomposition / live authoring | Optional follow-on | Editor-ergonomics upgrade. Authoring works today via Directus over the JSON-backed schema. No parity/security debt. |
| CSP Report-Only → enforce flip | Release-gate task | Land `/csp/report` (V2-F-02), soak, then `CSP_ENFORCE=1` (V2-F-01). Timeline in `cutover-plan.md` §5.3. |
| Deferred security hardening | Tracked | V2-F-04 (SRI + exact mermaid pin), V2-F-05 (audit moderator actions), V2-F-06 (upload rate-limit + multi-offset sniff), V2-F-07 (narrow `--forwarded-allow-ips`). All MED/LOW; none block cutover. |
| Doc consistency polish | Content task | The two content-quality MED items (quiz admonition keyword; `CACHE_BACKEND=redis` wording in two deployment pages). Cosmetic. |

---

## 8 · References

| Need | Source |
|---|---|
| The promote runbook (order, gates, rollback) | `docs/architecture/v2/cutover-plan.md` |
| Installer mechanics | `deploy.sh` |
| Day-two operations | `docs/RUNBOOK.md` |
| The 12-item plan + locked decisions | `docs/architecture/v2-plan.md` |
| The eight Phase 0 design contracts | `docs/architecture/v2/01`–`08` |
| Per-phase reports | `docs/architecture/v2/phase-1`–`phase-4b` |
| The built reference site | `docs-site/` (six sections, build green on node@22) |

v2 is complete pending the user's review and the two MUST-FIX items. `main`
remains untouched; nothing has been pushed.
