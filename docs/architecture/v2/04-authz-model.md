# v2/04 — Authorization Model (SSO + Roles + Permissions)

> Phase 0 · **DESIGN ONLY**. No code changes, no migration runs here. This is the
> contract Phase 2b (authZ) and Phase 4 (Directus) build against. Coordinates with
> `v2/03-data-model.md` (schema) and `v2/05-config-cms.md` (config + Directus map).
> Covers plan item **8 — SSO + authorization roles**.
>
> Owner: AuthZ-model agent. Branch `v2`. `main` untouched.

All file:line references are to the **current** tree under
`quiz-certification/` (which the audit confirms is the *entire* backend, not just
the quiz module — see `docs/architecture/v2-plan.md:8`). Phase 1 renames it to
`backend/`; this doc names target locations as `core/…` / `modules/…` where Phase
2b will land the code.

---

## 0. Scan box

- **Two role systems exist and do not connect.** `roles.py` stores *persona* values
  (`pm`/`ba`/`architect`…) in `users.role`; `main.py` authorises against *capability*
  strings (`QuizManager`/`FeedCreator`/`Moderator`/`User`) that no persona ever maps
  to. Net effect in production: an onboarded user has `role="architect"`, fails every
  `require_role([...])` check, and silently has **no** elevated access.
- **Dev mode hands everyone the keys.** `upsert_user` writes `role="QuizManager"`
  for every user when `DEV_MODE=true` (`storage.py:74`, `storage.py:84`), and
  `require_role` treats `QuizManager` as a global bypass (`auth.py:129`). Locally,
  every account is a full admin.
- **There is no way to grant a capability role.** The only writer of `users.role` is
  `set_user_role` at onboarding (`main.py:279`), and it only accepts persona keys.
  No admin API, no UI, no seed for the first real admin.
- **Target = two planes.** Learner-plane (FastAPI + Google SSO): `Learner`,
  `Feed Contributor`. Staff-plane (Directus): `Content Author`, `Quiz Admin`,
  `Feed Moderator`, `Platform Admin`. Personas move to a non-authorising
  `persona` profile attribute that only drives quiz-difficulty recommendation.
- **SSO needs hardening.** No PKCE, no `id_token`/`nonce` verification, domain
  enforced only by the Google `hd` *hint* plus `is_allowed_email`, and the session
  cookie sets **no** `Secure`/`HttpOnly`/`SameSite` flags (`main.py:61`).

---

## 1. Current state (with file:line)

### 1.1 System A — persona roles (`roles.py`)

`roles.py:9-19` defines nine persona roles, each carrying a recommended quiz level:

| key | label | level |
|---|---|---|
| `pm` | Project Manager | beginner |
| `ba` | Business Analyst | beginner |
| `qa` | QA / Test | beginner |
| `sales` | Sales / Pre-sales | beginner |
| `design` | Designer | beginner |
| `devops` | DevOps / Platform | advanced |
| `coder` | Engineer / Coder | advanced |
| `architect` | Architect | advanced |
| `other` | Other | beginner |

- `recommended_level(role_key)` (`roles.py:28-32`) maps a persona → `beginner` /
  `advanced`. This is the **only** real consumer of `users.role`; the home page reads
  it at `main.py:163` (`recommended = roles.recommended_level(user["role"])`) and
  `roles.label_for` is used for display at `main.py:172`, `main.py:483`.
- These persona keys are written into `users.role` by the onboarding flow:
  `onboarding_role_save` validates with `roles.is_valid(role)` (`main.py:271`) then
  calls `storage.set_user_role(user["email"], role)` (`main.py:279`). The picker UI
  iterates `roles.ROLES` in `templates/onboarding_role.html:23-32`.

So in production, a successfully onboarded user has `users.role ∈ {pm, ba, qa,
sales, design, devops, coder, architect, other}`.

### 1.2 System B — capability roles (`main.py` + `auth.py`)

`require_role(allowed_roles)` (`auth.py:107-136`) is the runtime gate. It:

1. pulls `request.session["user"]` (`auth.py:110`); 401-or-redirect if missing
   (`auth.py:111-115`),
2. re-reads the DB user via `storage.get_user(email)` (`auth.py:122`),
3. resolves `user_role = db_user.get("role") or "User"` (`auth.py:126`),
4. **bypasses all checks if `user_role == "QuizManager"`** (`auth.py:129-130`),
5. else requires `user_role in allowed_roles` (`auth.py:132-133`).

Every protected route and the exact capability strings it demands:

| Route | Method | `require_role([...])` | file:line |
|---|---|---|---|
| `/admin/attempts` | GET | `["QuizManager"]` | `main.py:515` |
| `/api/feed/flag` | POST | `["User","FeedCreator","Moderator","QuizManager"]` | `main.py:622` |
| `/api/feed` | POST | `["FeedCreator"]` | `main.py:650` |
| `/api/moderate/queue` | GET | `["Moderator"]` | `main.py:682` |
| `/api/moderate/action` | POST | `["Moderator"]` | `main.py:694` |
| `/api/admin/questions` | POST | `["QuizManager"]` | `main.py:741` |
| `/api/media/upload` | POST | `["FeedCreator"]` | `main.py:756` |

The capability vocabulary in use is therefore exactly: **`User`, `FeedCreator`,
`Moderator`, `QuizManager`**. `models.py:59` documents the same set in a comment:
`# e.g., 'FeedCreator', 'Moderator', 'QuizManager', 'User'`. `users.role` is a
`String(32)` (`models.py:59`) — a single free-text column, so a user holds **one**
role at a time.

### 1.3 The missing mapping (the core defect)

`set_user_role` (`storage.py:91-97`) writes whatever onboarding gives it — a persona
key — verbatim into `users.role`. There is **no** translation layer from persona →
capability anywhere in the codebase. Consequently:

- In **production**, `upsert_user` creates new users with `role=None`
  (`storage.py:74`: `role = "QuizManager" if config.DEV_MODE else None`). After
  onboarding the value becomes e.g. `"architect"`. At every gate, `auth.py:126`
  resolves `"architect"` (not `None`, so the `or "User"` default doesn't even apply),
  it is not `"QuizManager"`, and `"architect" not in ["FeedCreator"]` →
  **403 on every protected action**. A production Architect cannot post to the feed,
  moderate, upload media, or manage questions. The capability system is effectively
  dead in prod.
- An un-onboarded prod user (`role=None`) resolves to `"User"` (`auth.py:126`), which
  only satisfies `/api/feed/flag`.

### 1.4 Dev-mode auto-elevation

`upsert_user` assigns `role="QuizManager"` to **every** user when `DEV_MODE=true`
(`storage.py:74`) and re-asserts it for existing users with no role (`storage.py:84`:
`if config.DEV_MODE and not u.role: u.role = "QuizManager"`). Because `QuizManager`
is the global bypass (`auth.py:129`), **every dev login is a full administrator**.
This also means dev never exercises the persona-onboarding path in a way that matches
prod, which is why the System-A/System-B disconnect went unnoticed. `DEV_MODE`
defaults to **true** (`config.py:19`).

### 1.5 The assignment gap

- The *only* writer of `users.role` outside dev auto-elevation is onboarding
  (`main.py:279`), and it is hard-wired to persona keys via the picker
  (`templates/onboarding_role.html:23-32`) and `roles.is_valid` (`main.py:271`).
- There is **no** admin endpoint to set a capability role, no Directus, and no
  bootstrap for the first admin. In a fresh prod deployment, **nobody** can ever
  obtain `FeedCreator`/`Moderator`/`QuizManager` — the only path to those strings is
  to edit Postgres by hand.

### 1.6 SSO posture (current)

- **Flow:** authorization-code, built by hand in `auth.py`. `google_authorize_url`
  (`auth.py:43-54`) requests `response_type=code`, scope `openid email profile`,
  passes `state` and `hd=ALLOWED_DOMAIN`. `exchange_code_for_user`
  (`auth.py:57-98`) POSTs the code to the token endpoint, then calls the **userinfo**
  endpoint with the access token and reads `email`/`name`/`picture`.
- **No PKCE.** No `code_verifier`/`code_challenge` anywhere (verified by grep; the
  only `nonce` occurrences are AES-GCM payload crypto in `encryption.py`).
- **No `id_token` verification.** The returned ID token is ignored; identity is taken
  from a second userinfo round-trip rather than a verified JWT. No `nonce`.
- **Domain enforcement is soft.** `hd` is a *hint* Google may ignore; the real check
  is `is_allowed_email` (`auth.py:18-25`), applied to the userinfo `email`
  (`auth.py:92`). `ALLOWED_DOMAIN` defaults to `deptagency.com` (`config.py:25`) and
  **empty means no restriction** (`auth.py:23-24`) — a fail-open default if the env
  var is ever blanked. Google's verified-email signal (`email_verified`) is not
  checked.
- **State** is stored in the session pre-redirect (`main.py:218`) and compared on
  callback (`main.py:226`). This is fine, but it lives in a cookie with no integrity
  flags (next point).
- **Session cookie.** `SessionMiddleware(secret_key=config.SECRET_KEY)`
  (`main.py:61`) — **no** `https_only`, `httponly` (Starlette's `SessionMiddleware`
  cookie is HttpOnly by default, but is **not** marked `Secure`), `same_site`, or
  `max_age` configured. `SECRET_KEY` defaults to a hardcoded literal
  (`config.py:22`). CORS allows credentials from `localhost:8080` (`main.py:54-60`).
- **Dev login** bypasses Google entirely: `/login/dev` accepts any allowed-domain
  email on a form (`main.py:188-210`, `templates/login.html:16-25`) and, via
  `upsert_user`, auto-elevates (§1.4).

---

## 2. Target role taxonomy (GATE decision)

> **GATE — confirm or flip at the Phase 0 gate.** The default below is the two-plane
> split from `v2-plan.md:112`. The alternative (single unified RBAC) and its
> tradeoffs are in §2.3.

### 2.1 Default — two planes, six roles, personas demoted

**Learner-plane** — authenticate to the FastAPI app via Google SSO; identity +
runtime authorisation enforced by FastAPI; role stored in `users.role`:

| Role | `users.role` value | Purpose |
|---|---|---|
| **Learner** | `learner` (default) | The baseline. Read course + feed, take the quiz, earn/download own certificate, flag feed content. Every authenticated app user is at least this. |
| **Feed Contributor** | `feed_contributor` | Learner + may *create* feed posts and upload media. UGC scenarios they submit still queue for moderation. Granted by a Platform Admin (§7). |

**Staff-plane** — authenticate to **Directus** (its own login over the shared
Postgres); authoring/config/moderation tooling lives in Directus; where a staff role
also needs to act inside the FastAPI runtime, it is *mirrored* into `users.role`
(§4.3):

| Role | Directus role | `users.role` mirror | Purpose |
|---|---|---|---|
| **Content Author** | `Content Author` | `content_author` | Create/edit course chapters, framework, framework-explainer. Authoring is done in Directus; FastAPI serves the result read-only. |
| **Quiz Admin** | `Quiz Admin` | `quiz_admin` | Create/update questions, approve UGC scenario questions, view admin attempts. Replaces today's `QuizManager` *for quiz scope only* (no longer a global god-mode). |
| **Feed Moderator** | `Feed Moderator` | `feed_moderator` | View the moderation queue, approve/flag/remove feed items and questions. Replaces today's `Moderator`. |
| **Platform Admin** | `Platform Admin` (admin) | `platform_admin` | Superuser across both planes: assign roles, write config/secrets, full Directus admin, all of the above. The *only* role that bypasses checks. |

Design rules:
- **`learner` is the floor, not a special case.** `require_*` defaults an
  authenticated-but-roleless user to `learner` (replacing today's `or "User"`
  default at `auth.py:126`), so the System-A/System-B gap cannot recur.
- **`platform_admin` is the single global bypass.** `quiz_admin` no longer bypasses
  everything (today `QuizManager` does — `auth.py:129`). Scope creep is removed.
- **Two-role reality.** A person can be both a learner and staff (e.g. an Architect
  who authors content *and* takes the quiz). `users.role` holding one capability
  string cannot express this cleanly. See §2.2 for the storage decision.

### 2.2 Capability storage — single column vs. a roles set (sub-decision)

Today `users.role` is one `String(32)` (`models.py:59`). Two options for v2; this is
a **schema coordination point with `v2/03-data-model.md`**:

- **Option A (recommended): a `user_roles` set.** Add a `user_roles(user_email,
  role)` join table (or a `roles text[]` column) so a user can hold
  `{learner, content_author}` simultaneously. `require_*` checks set-membership.
  Cleanly models the architect-who-also-authors. Migration: backfill from the
  current single `users.role` (§5.2).
- **Option B (minimal): keep one `users.role` string** but make it a *capability*
  enum and add a separate `persona` column. Simpler migration, but cannot represent
  learner+staff overlap; staff who also take the quiz would need their learner access
  inferred from "any authenticated user is ≥ learner", which works for read/quiz but
  is awkward if staff roles are meant to *exclude* the learner floor.

**Recommendation:** Option A. It is the only one that models real DEPT® staff (an
architect authors *and* certifies). The permission matrix (§3) is written against a
role *set*; with Option B, `platform_admin` simply implies the rest.

### 2.3 Alternative taxonomy — single unified RBAC (the flip)

Instead of two planes, run **one** RBAC system in FastAPI and use Directus purely as
a headless content store (its own admin login reserved for break-glass schema work,
not day-to-day editing). Roles: `learner`, `feed_contributor`, `content_author`,
`quiz_admin`, `feed_moderator`, `platform_admin` — all in `users.role(s)`, all
authenticated via Google SSO, authoring screens built inside the FastAPI app.

| | Two-plane (default) | Unified RBAC (alternative) |
|---|---|---|
| Authoring UI | Directus gives it for free (CRUD, asset mgmt, audit, REST/GraphQL) | Must be built in the buildless FE — large effort |
| Where staff log in | Directus (staff) + Google SSO (learner) — two front doors | One front door (Google SSO) |
| Enforcement surface | Split: Directus enforces authoring/config; FastAPI enforces runtime | Single: FastAPI enforces everything |
| Risk of double-enforcement ambiguity | **Higher** — must draw a crisp boundary (§4.4) | Lower |
| Audit trail | Directus provides it for content/config out of the box | Must be built |
| Onboarding new editors | Directus user management | Custom admin screens |
| Alignment with locked decisions | Matches `v2-plan.md:26` (Directus = staff/editor plane) | Contradicts the locked CMS decision |

**Default stands** (two-plane) because the CMS-over-Postgres decision is already
locked (`v2-plan.md:24-28`) and buying authoring + audit + asset management from
Directus is the whole point of adopting it. The unified-RBAC flip is only attractive
if the gate decides Directus should be headless-only.

---

## 3. Permission matrix

### 3.0 Locked vocabulary (this doc owns it)

This document is the **owner** of the permission-string and role-key vocabulary
for v2. `07-security-baseline.md` and every other doc sweep to match. Locked
forms below — any drift in a sibling doc is a bug against this section, not a
parallel design.

**Permission strings — dotted lower-case, `resource.verb`:**

| Permission | Held by | Notes |
|---|---|---|
| `feed.create` | `feed_contributor` | Post to the feed. |
| `feed.flag` | `learner`, `feed_contributor`, `content_author`, `quiz_admin`, `feed_moderator` | Any authenticated user. |
| `moderate.view` | `feed_moderator` | View the moderation queue. |
| `moderate.action` | `feed_moderator` (+ `quiz_admin` for question UGC) | Approve / flag / remove. |
| `question.write` | `quiz_admin` | Create/edit question text. |
| `media.upload` | `feed_contributor`, `content_author` | Feed media (FC) + course media via Directus (CA). |
| `attempts.view` | `quiz_admin` | Admin attempts dashboard. |
| `config.read`, `config.write` | (empty set) | `platform_admin` only — via the implicit bypass. |
| `role.assign` | (empty set) | `platform_admin` only — via the implicit bypass. |

`platform_admin` implicitly holds every permission and is checked first
(§3 implementation block). It is **not** listed in the "held by" sets above
because it is the single global bypass, not a per-permission grant.

**Role keys — snake_case:**

`learner`, `feed_contributor`, `content_author`, `quiz_admin`,
`feed_moderator`, `platform_admin`.

Display labels (`Content Author`, `Feed Moderator`, …) are UI-only and live in
Directus role config / a small Python label map. They never appear in code that
authorises.

### 3.1 The matrix

Columns are the **default** roles plus `anonymous`. `platform_admin` is a superset
(allow-all) and is shown explicitly for completeness. Cells: ✅ allow · ❌ deny ·
✅* allow-with-condition (see note). "Plane / enforcer" says **where** the rule is
enforced so there is no ambiguity (§4.4).

Legend for enforcer: **F** = FastAPI runtime (`require_*` dependency); **D** =
Directus RBAC; **F+D** = both (FastAPI for the learner-facing API, Directus for the
authoring/admin tool that writes the same data).

| # | Action / resource | Plane / enforcer | anonymous | learner | feed_contributor | content_author | quiz_admin | feed_moderator | platform_admin | Notes |
|---|---|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|---|
| 1 | Quiz **start** (`/quiz/start`) | F | ❌ | ✅* | ✅* | ✅* | ✅* | ✅* | ✅* | *requires a persona set + cooldown clear (`main.py:311`,`main.py:315`). Any authenticated user may take the quiz. |
| 2 | Quiz **submit** (`/quiz/submit`) | F | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Owner-bound: `active.user_email == session email` (`main.py:371`). |
| 3 | Quiz **take page** (`/quiz/take`) | F | ❌ | ✅* | ✅* | ✅* | ✅* | ✅* | ✅* | *redirects to onboarding if no persona (`main.py:452-453`). |
| 4 | Certificate **download** own (`/certificate/{id}`) | F | ❌ | ✅* | ✅* | ✅* | ✅* | ✅* | ✅* | *only your own cert — loop is over `attempts_for(session email)` (`main.py:470`). Not an ownership check by `cert_id` alone; keep that. **`platform_admin` uses the same ownership loop — there is no admin "download anyone's cert" surface in v2.** Out-of-band recovery (e.g. a lost cert) goes via the verify endpoint (row 5) plus a re-issue from `attempts` data, not via an admin download route. |
| 5 | Certificate **verify** (`/verify`, `/verify/{id}`) | F (public) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Intentionally public (`main.py:488`,`main.py:507`). Returns validity, not the PDF. Keep anonymous. |
| 6 | Feed **read** (`/api/feed`) | F | ✅/❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Today open to all incl. anonymous (`main.py:615` has no guard). **GATE micro-decision:** keep feed public, or require ≥ learner. Default: require ≥ learner (feed is internal DEPT® content). |
| 7 | Feed **create** (`/api/feed`) | F | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | Today `["FeedCreator"]` (`main.py:650`) → `feed_contributor`. Scenario UGC still enters `pending_review` (`main.py:668`). |
| 8 | Feed **flag** (`/api/feed/flag`) | F | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Today `["User","FeedCreator","Moderator","QuizManager"]` (`main.py:622`) → any authenticated user. |
| 9 | Moderation **queue view** (`/api/moderate/queue`) | F+D | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | Today `["Moderator"]` (`main.py:682`). Mirrored in Directus as a curated moderation view. |
| 10 | Moderation **action** (`/api/moderate/action`) | F+D | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | Today `["Moderator"]` (`main.py:694`). Approve/flag/remove feed + questions. |
| 11 | Question **create/update** (`/api/admin/questions`) | F+D | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | Today `["QuizManager"]` (`main.py:741`). In v2 authored in Directus; the API stays for programmatic/seed writes. |
| 12 | Question **UGC approve** (`/api/moderate/action`, type=question) | F+D | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | UGC scenario→question (`main.py:711-722`). **GATE micro-decision:** does approving a *quiz question* belong to `feed_moderator` (content safety) or `quiz_admin` (pedagogy)? Default: **both** may approve; only `quiz_admin` may *edit* the question text. |
| 13 | Course **read** (`/api/course/*`) | F | ✅/❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Today fully open (`main.py:551`,`main.py:560`,`main.py:567`,`main.py:576`). **GATE micro-decision:** public vs. ≥ learner. Default: ≥ learner (matches feed). |
| 14 | Course **authoring / edit** (chapters, framework, explainer) | D (+F seam) | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | No write API exists today (only `storage.save_chapter`/`save_framework*` called by the ETL). In v2 this is **Directus-owned**; FastAPI exposes read-only + a CMS webhook/read adapter (`modules/cms/`). |
| 15 | Media **upload** (`/api/media/upload`) | F | ❌ | ❌ | ✅ | ✅* | ❌ | ❌ | ✅ | Today `["FeedCreator"]` (`main.py:756`). `feed_contributor` for feed media; *content_author may upload course media via Directus assets (D), see §4*. |
| 16 | Media **stream** (`/media/video/{id}`, `/media/image/{id}`) | F | ✅/❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Today unguarded (`main.py:812`,`main.py:850`). **Security note:** asset IDs are UUIDs but enumeration/hotlinking is possible. **GATE micro-decision:** require ≥ learner (default) vs. public. |
| 17 | Config **read** (Google/LLM/runtime settings) | F+D | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | New in v2 (`v2/05-config-cms.md`). Admin-only. |
| 18 | Config **write** (rotate keys, toggles) | F+D | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Platform Admin only. Audited (§7.4). |
| 19 | **Role assignment** (grant/revoke roles) | F+D | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | New (§7). Learner→feed_contributor via app admin screen; staff roles via Directus. Audited. |
| 20 | Admin **attempts view** (`/admin/attempts`) | F | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | Today `["QuizManager"]` (`main.py:515`). Reassigned to `quiz_admin` (it is quiz analytics). |
| 21 | **Directus admin** (collections, users, roles, settings) | D | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Directus's own admin. Only `platform_admin` (mapped to Directus admin role). |
| 22 | Auth **self** (`/auth/me`, `/auth/session-key`) | F | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Any authenticated session (`main.py:521`,`main.py:139`). |

`✅/❌` in the anonymous column marks rows whose public-vs-authenticated status is a
**GATE micro-decision** (rows 6, 13, 16) — today they are open; the recommended
default tightens them to ≥ learner. Certificate verify (row 5) **stays public** by
design.

**Implementation shape.** Replace the single bypass-on-`QuizManager` logic
(`auth.py:129`) with a small permission layer:

```
# core/auth/permissions.py (Phase 2b)
PERMISSIONS = {                       # permission -> set of roles that hold it
    "feed.create":      {"feed_contributor"},
    "feed.flag":        {"learner","feed_contributor","content_author",
                          "quiz_admin","feed_moderator"},
    "moderate.view":    {"feed_moderator"},
    "moderate.action":  {"feed_moderator"},          # + quiz_admin for questions
    "question.write":   {"quiz_admin"},
    "media.upload":     {"feed_contributor","content_author"},
    "attempts.view":    {"quiz_admin"},
    "config.read":      set(),  "config.write": set(),
    "role.assign":      set(),
    # platform_admin implicitly holds everything (checked first)
}

def require_permission(perm: str):
    def dep(request: Request) -> dict:
        u = _session_user_or_401(request)               # was auth.py:110-119
        held = users_service.roles_for(u["email"])      # set[str]; never None
        if "platform_admin" in held:                    # single global bypass
            return u
        if held & PERMISSIONS.get(perm, set()):
            return u
        raise HTTPException(403, "Insufficient permissions")
    return dep
```

`users_service.roles_for(email) -> set[str]` is the **only** read path for a
user's capability roles in v2. It reads from the `user_roles` join table
(canonical schema, owned by `v2/03-data-model.md` §2.2) and returns at least
`{"learner"}` for any authenticated user (the learner floor, §2.1) — never
`None`, never an empty set. Direct reads of `db_user["roles"]`, `db["roles"]`,
or a `users.roles text[]` column are **forbidden** in v2 code; sketches in this
doc go through the helper so the schema-of-record stays in 03.

Routes then read as `Depends(require_permission("feed.create"))` instead of
hard-coding role strings — decoupling endpoints from the taxonomy so a future role
change is a one-line edit to `PERMISSIONS`, not a sweep of `main.py`. `require_role`
can remain as a thin wrapper for backward-compat during the migration.

---

## 4. Two-plane model (precise)

### 4.1 Where each role authenticates

- **Learner-plane (`learner`, `feed_contributor`):** authenticate to the **FastAPI
  app** via Google SSO (the hardened flow, §6). Session is the FastAPI signed cookie
  (`main.py:61`). They never see Directus.
- **Staff-plane (`content_author`, `quiz_admin`, `feed_moderator`,
  `platform_admin`):** authenticate to **Directus** (separate Node service over the
  same Postgres, `v2-plan.md:26`) to do authoring / moderation / config in the
  Directus admin UI. Directus enforces its own RBAC there.

### 4.2 Do staff also use Google SSO into Directus?

**Recommended default: yes — Directus uses Google SSO (OpenID Connect / OAuth2 SSO)
with the same `deptagency.com` domain restriction**, so staff have one identity
provider and there is no second password to manage. Directus supports external SSO
providers; configure a Google provider scoped to the workspace domain
(coordinate exact env in `v2/05-config-cms.md`). Staff who *also* take the quiz log
into the FastAPI app with the same Google account; their two identities are joined by
**email** (the `users` PK is `email`, `models.py:56`). Break-glass: keep **one**
local Directus admin (env-seeded) for when SSO is down.

### 4.3 How a Platform Admin is represented in both

A `platform_admin` is:
- a **Directus user in the Directus admin role** (full Directus admin — row 21), and
- mirrored into FastAPI as a `user_roles` row `(email, "platform_admin")`
  (canonical schema, `v2/03-data-model.md` §2.2) so the FastAPI runtime also
  treats them as superuser (single bypass in §3's `require_permission` via
  `users_service.roles_for(email)`).

Keep these in sync via the **role-assignment service** (§7): assigning
`platform_admin` writes both the Directus role membership and the
`user_roles` mirror, keyed by email. The mirror is **one-way: Directus → app**
(§7.2). The seed admin(s) from the env allowlist (§7.3) are created in both
places at bootstrap.

### 4.4 The enforcement boundary (no double-authoritative ambiguity)

To avoid two systems each thinking they own a decision:

- **Directus is authoritative for *authoring + config + moderation tooling*** — i.e.
  *who can edit course content, questions, framework, config, and operate the
  moderation console*. Rows 9–14, 17–19, 21 are **owned** by Directus RBAC when the
  action happens *through Directus*.
- **FastAPI is authoritative for *runtime, learner-facing actions*** — quiz
  start/submit/take, certificate issue/download/verify, feed read/create/flag, media
  stream, self endpoints. Rows 1–8, 16, 20, 22.
- **Shared-data rows (9–14) are enforced *per entry point*, never twice for one
  call.** Example: a question can be written two ways — (a) a Content/Quiz editor in
  the Directus UI → **Directus** authorises; (b) the `/api/admin/questions` API →
  **FastAPI** `require_permission("question.write")` authorises. Both write the *same*
  `questions` table, but a single request only ever crosses one gate. The matrix's
  `F+D` marks "this resource is reachable from both planes," **not** "checked twice in
  one request."
- **Rule of thumb:** *The plane that receives the HTTP request enforces it.* FastAPI
  never calls Directus to ask permission, and Directus never calls FastAPI. They agree
  because both read the same role facts (Directus role membership ↔ the
  FastAPI-side `user_roles` mirror), kept consistent by §7.
- **`modules/cms/` is a read/webhook seam only** (`v2-plan.md:40`): it ingests
  Directus content changes (webhook → cache invalidation / read adapter). It performs
  **no** authorisation — by the time content reaches FastAPI it is already authored
  and approved.

---

## 5. Persona-as-profile reframing

### 5.1 What changes

The nine persona keys (`roles.py:9-19`) stop being authorisation roles and become a
**profile attribute** whose *only* job is driving quiz-difficulty recommendation
(`recommended_level`, `roles.py:28`). Concretely:

- Add a `persona` field to the user profile, separate from capability roles.
  Coordinate exact shape with `v2/03-data-model.md` — **recommended:** a
  `users.persona VARCHAR(32)` column (nullable) holding a persona key, plus keep
  `roles.py` as the persona *catalogue* (label/level/blurb) renamed conceptually to a
  "persona registry". The `users.role(s)` capability storage (§2.2) is now disjoint
  from persona.
- Onboarding (`main.py:267-281`, `templates/onboarding_role.html`) writes
  `users.persona` via a new `set_user_persona(email, persona)` instead of
  `set_user_role`. The picker copy already says "so we can recommend the right level"
  (`templates/onboarding_role.html:11-13`) — it was always a recommendation
  mechanism, never an access control, so the UI barely changes (only the storage
  target and the function name).
- The home page reads `recommended_level(user["persona"])` instead of
  `user["role"]` (today `main.py:163`), and `label_for(user["persona"])` for display
  (today `main.py:172`, `main.py:483`).
- Capability is **never** inferred from persona. An `architect` persona grants no
  extra access; staff capability comes only from a granted role (§7).

### 5.2 Migration rules for existing `users.role` values

The current `users.role` column is a mix: some rows hold a persona key (prod
onboarded users), some hold `QuizManager` (dev auto-elevation, `storage.py:74`), some
hold `None` (un-onboarded prod). The migration (executed in Phase 2b, schema from
Phase 2a — **coordinate with `v2/03-data-model.md`**) splits this one column into
`persona` + `roles`:

| Current `users.role` | New `persona` | New `roles` (Option A set) | Rationale |
|---|---|---|---|
| `pm`/`ba`/`qa`/`sales`/`design`/`devops`/`coder`/`architect`/`other` | same value | `{learner}` | It was a persona all along; everyone is a learner. |
| `QuizManager` | `NULL` (prompt at next login) | `{learner}` **by default** | This was *dev auto-elevation*, **not** a deliberate grant. **Do not** migrate it to `quiz_admin`/`platform_admin` — that would silently promote every dev account. Real admins are (re)granted from the env allowlist (§7.3). |
| `FeedCreator` | `NULL` | `{learner, feed_contributor}` | Deliberate-looking capability → preserve as contributor. (Note: grep shows no current writer ever sets this string outside manual DB edits; handle defensively anyway.) |
| `Moderator` | `NULL` | `{learner, feed_moderator}` | Preserve moderator intent. |
| `User` | `NULL` | `{learner}` | Baseline. |
| `NULL` / empty | `NULL` | `{learner}` | Un-onboarded; persona collected at next onboarding. |

Hard rules:
1. **`QuizManager` → `{learner}` only. No admin auto-grant. Emit a migration
   report.** `QuizManager` is the dev-mode artefact (§1.4); the migration writes
   `roles = {learner}` for every former-`QuizManager` row and leaves `persona`
   `NULL` (collected at next onboarding). It **MUST NOT** be mapped to
   `quiz_admin`, `platform_admin`, or any other elevated role — doing so
   re-introduces the exact over-privilege v2 removes. Real admins are seeded
   explicitly via `ADMIN_EMAILS` (§7.3); the migration emits a CSV report
   listing every former-`QuizManager`, `Moderator`, and `FeedCreator` email so a
   `platform_admin` can re-grant deliberately after cutover. This rule is the
   schema/authZ boundary for `v2/03-data-model.md` §3 step 5 + §8 step 7 (the
   schema doc adopts the same rule by reference).
2. **Idempotent + reversible — via backup snapshot, not a column.** Rollback is
   driven by the pre-migration backup taken in §8 step 1 (full DB snapshot
   before the Alembic revision runs), **not** by a `users.legacy_role` column.
   The migration is itself idempotent (re-running against an already-split row
   is a no-op) and emits a CSV report (former `users.role` → new `persona` +
   `roles`) for human review; that CSV plus the snapshot is sufficient to
   re-derive the prior state.
3. **No data loss** (hard constraint, `v2-plan.md:118`): personas are preserved
   verbatim; capability is reset to least-privilege and re-granted deliberately.

---

## 6. SSO hardening

All of the following land in `core/auth/` (Phase 2b). They replace/augment
`auth.py` and the OAuth routes in `main.py`.

### 6.1 PKCE on the Google code flow

Add PKCE (RFC 7636) to the authorization-code flow. The PKCE verifier, OAuth
`state`, and `nonce` ride in a **short-lived signed pre-auth cookie** —
**not** in the long-lived (8h) session cookie. Two reasons: (a) the verifier
must not survive past the callback (theft window widens otherwise), and (b)
shipping ~80 extra bytes on every authenticated request for the rest of the
session is pure bloat.

1. **Generate per-attempt** (in `/auth/google`, replacing the bare-state logic
   at `main.py:217-219`):
   - `code_verifier = secrets.token_urlsafe(64)` (43–128 chars, high-entropy).
   - `code_challenge = base64url( SHA256(code_verifier) )`, no padding.
   - `state = secrets.token_urlsafe(32)`, `nonce = secrets.token_urlsafe(32)`.
   - Pack `{code_verifier, state, nonce}` into a separate **pre-auth cookie**:

     ```
     response.set_cookie(
         "aoc_preauth",
         signer.dumps({"v": code_verifier, "s": state, "n": nonce}),
         max_age=300,                # 5 minutes — covers the round-trip only
         httponly=True,
         secure=not config.DEV_MODE,
         samesite="lax",
         path="/auth/",              # scoped to the OAuth endpoints only
     )
     ```

     Signed with `itsdangerous.URLSafeTimedSerializer(SECRET_KEY)` (already a
     dependency). Server-side only — the verifier never reaches application
     JS.
2. **On `google_authorize_url`** (`auth.py:43-54`) add:
   `code_challenge=<challenge>`, `code_challenge_method=S256`, and
   `nonce=<nonce>`.
3. **On `/auth/google/callback`**:
   - Read + verify the `aoc_preauth` cookie (signature, 5-min max-age via the
     serializer).
   - Compare `state` from the cookie to the `state` querystring param.
   - POST the token exchange (`exchange_code_for_user`, `auth.py:67-77`) with
     `code_verifier` from the cookie. Google rejects the exchange if it
     doesn't hash to the original challenge — defeating code
     interception/replay.
   - Verify the returned `id_token` nonce claim against `nonce` from the
     cookie (§6.3).
   - **Delete the pre-auth cookie** (`response.delete_cookie("aoc_preauth",
     path="/auth/")`) before issuing the long-lived session.
4. The 8-hour session cookie (§6.4) carries *only* `{email, ...profile}` —
   no `code_verifier`, no `state`, no `nonce`. The pre-auth and session
   cookies are two distinct cookies with two distinct lifetimes.

> **Note on COOP and OAuth shape (DEFER, Phase 2b):** the
> `Cross-Origin-Opener-Policy: same-origin` header that
> `v2/07-security-baseline.md §3.2` ships would **break a popup-based OAuth
> flow** — the popup loses its `window.opener` reference and cannot post the
> result back. The v2 flow above uses a **top-level redirect** (the existing
> `/auth/google` → Google → `/auth/google/callback` shape), which is
> unaffected by COOP. If a future change ever proposes a popup OAuth, it
> must coordinate with 07 §3.2 to relax COOP for the affected origin (or
> switch to `same-origin-allow-popups`). Track as a Phase 2b regression
> check.

### 6.2 Strict server-side domain enforcement

- Keep `hd=ALLOWED_DOMAIN` as a *hint* (`auth.py:51`) but treat it as untrusted.
- **Enforce on the server** against the verified ID token (next point): require
  `email_verified == true` **and** `hd == ALLOWED_DOMAIN` (Google sets the `hd` claim
  for Workspace accounts) **and** the email domain equals `ALLOWED_DOMAIN`
  (tighten `is_allowed_email`, `auth.py:18-25`).
- **Fix the fail-open default.** Today empty `ALLOWED_DOMAIN` means "no restriction"
  (`auth.py:23-24`). In v2, an **empty `ALLOWED_DOMAIN` in a non-dev environment is a
  startup error** (config validation in `v2/05-config-cms.md`); empty is only
  tolerated in `DEV_MODE`.
- Reject the login if `hd`/`email_verified` are absent for a non-dev environment.

### 6.3 State + nonce + ID-token verification

- **State:** keep the CSRF state compare (`main.py:226`) but bind it to the hardened
  cookie (§6.4) so it can't be tampered with.
- **Nonce:** generate per-attempt (§6.1), send in the auth request, and **verify it
  matches the `nonce` claim** in the returned ID token. Defeats ID-token replay.
- **Verify the `id_token` as a JWT** (currently ignored — identity comes from a
  userinfo round-trip, `auth.py:83-90`): validate signature against Google's JWKS,
  `iss ∈ {accounts.google.com, https://accounts.google.com}`, `aud == GOOGLE_CLIENT_ID`,
  `exp`/`iat` fresh, then read `email`/`email_verified`/`hd`/`name`/`picture` from the
  **verified** claims. Drop the second userinfo call (or keep it only as a fallback).
  This needs a JWT/JWKS verifier — add `google-auth` (or `authlib`, `PyJWT[crypto]`);
  `cryptography` is already present (requirements). Today only
  `itsdangerous`/`requests`/`cryptography` are pinned — no JWT lib — so this is a new
  dependency decision noted for `v2/05-config-cms.md`.

### 6.4 Session cookie flags (env-tied)

Replace `app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)`
(`main.py:61`) with explicitly-flagged middleware:

```
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,            # must be env-provided in prod (no default)
    session_cookie="aoc_session",
    same_site="lax",                          # Lax: survives the Google redirect-back GET
    https_only=not config.DEV_MODE,           # Secure flag ON in prod, OFF on http://localhost
    max_age=60 * 60 * 8,                      # 8h absolute lifetime — LOCKED
)
```

`max_age = 8 hours` is **locked** per Phase 0 gate decision Q-1 (the
security-stronger default; matches typical SSO discipline). This is the
single source of truth for session cookie lifetime in v2;
`v2/07-security-baseline.md §4.1` syncs to this value. Any future change is a
gate decision, not a doc-local edit.

- `HttpOnly` is set by Starlette's `SessionMiddleware` by default — keep it (the JS
  payload key is fetched via `/auth/session-key`, `main.py:139`, not read from the
  cookie, so HttpOnly is safe).
- `SameSite=Lax` (not `Strict`) because the OAuth callback returns via a top-level GET
  navigation; `Strict` would drop the session on return.
- `https_only` (the `Secure` flag) is tied to environment — **on** whenever
  `DEV_MODE=false`. Today no flag is set at all (verified).
- **`SECRET_KEY` must have no hardcoded default in non-dev** (today
  `config.py:22` ships a literal). Coordinate the secrets policy with
  `v2/05-config-cms.md` / `v2/07-security-baseline.md`.

### 6.5 How dev-mode login changes (no auto-elevation)

- `/login/dev` (`main.py:188-210`) stays as a convenience for `DEV_MODE=true` only
  (already gated, `main.py:191`), but `upsert_user` **must stop auto-assigning
  `QuizManager`** (`storage.py:74`, `storage.py:84`). New rule: dev users are created
  with `roles={learner}` like prod.
- To test elevated flows locally, use the **role-assignment API/seed** (§7) — e.g. an
  env `DEV_SEED_ADMINS=you@deptagency.com` that grants `platform_admin` *explicitly*
  at startup. This keeps dev and prod on the *same* code path (deliberate grants),
  killing the System-A/System-B blind spot (§1.4).
- Dev cookie is HTTP (`https_only=False`) so `localhost` works; everything else
  (PKCE, nonce, state) is exercised only in the real Google flow, which dev bypasses
  — acceptable, since prod is the enforced surface.

---

## 7. Role assignment

### 7.1 Mechanism

A single **role-assignment service** in `core/auth/` is the *only* writer of
capability roles, replacing today's onboarding-writes-role coupling (`main.py:279`,
which becomes persona-only per §5):

- `grant_role(actor, target_email, role)` / `revoke_role(...)` — validates the role
  is in the taxonomy, checks `actor` holds `role.assign` (i.e. is `platform_admin`),
  writes the `user_roles` join table (canonical capability storage, Option A,
  §2.2), and for staff roles also updates Directus role membership (§4.3), then
  writes an audit record (§7.4).

### 7.2 Where it surfaces

- **Staff roles** (`content_author`, `quiz_admin`, `feed_moderator`,
  `platform_admin`): managed in **Directus user management** (its native UI),
  since staff already live in Directus (§4.1). A Directus hook (or the
  `modules/cms/` seam) mirrors membership changes into the FastAPI-side
  `user_roles` table so runtime checks agree.

  **Mirror direction is one-way: Directus → app. Locked.** Directus is the
  authoritative source for staff-role membership; the app's `user_roles` rows
  for staff roles are a derived copy. FastAPI **never writes back** to
  Directus role membership for these roles. The only app-side writer of
  capability roles is `grant_role`/`revoke_role` for the *learner-plane*
  `feed_contributor` grant (next bullet) — which Directus does not own and
  therefore does not mirror. This rule prevents dual-write drift: any conflict
  between the two stores is resolved by re-reading Directus and overwriting
  the local copy, never the reverse.
- **`learner → feed_contributor`**: a small **app admin screen** in the FastAPI app
  (Platform-Admin-only), since feed contributors are learner-plane users who never log
  into Directus. Backed by a new endpoint, e.g.
  `POST /api/admin/roles` `{email, role, action}` guarded by
  `require_permission("role.assign")`.
- **No self-service elevation.** A learner cannot make themselves a contributor;
  onboarding only sets `persona` (§5).

### 7.3 Seeding the first Platform Admin

Bootstrap problem: a fresh DB has no admin, and the only role-writer requires an
admin. Solve with an **env allowlist**, coordinated with `v2/05-config-cms.md`:

- `ADMIN_EMAILS` (comma-separated, e.g. `modyyash@deptagency.com,...`). New config var
  (none exists today — verified: no `ADMIN_EMAILS`/allowlist anywhere).
- At startup (`_startup`, `main.py:72-74`) **and** at each login, any user whose email
  is in `ADMIN_EMAILS` is *ensured* to hold `platform_admin` in both planes
  (idempotent). This is the only place capability is granted without an existing
  admin acting.
- `DEV_SEED_ADMINS` plays the same role for `DEV_MODE` (§6.5), replacing blanket
  auto-elevation with an explicit, named allowlist.
- The allowlist is a *floor*, not a ceiling: removing an email from it does **not**
  auto-revoke (avoids lock-out churn); revocation is an explicit admin action (§7.1).

### 7.4 Audit trail

Every grant/revoke and every config write (rows 17–19) is recorded. Two sources:

- **Directus** provides an activity/revisions log out of the box for staff-role and
  content/config changes (one of the reasons it was chosen, `v2-plan.md:26`).
- **FastAPI** writes an `auth_audit` record for app-plane grants (learner→contributor)
  and admin API calls: `{actor_email, target_email, action, role, ts, source_ip}`.
  Coordinate the table with `v2/03-data-model.md`. This closes the gap that today
  there is **no record** of who changed a role (because nothing but onboarding ever
  could).

---

## 8. What Phase 2b implements (ordered checklist)

Sequenced; (2a) schema must land first where noted. Parity harness (`tests/baseline/`)
re-run at the gate.

1. **[2a coordination] Schema split.** With `v2/03-data-model.md`: add
   `users.persona`, the `user_roles` join table (canonical capability storage,
   Option A), and an `auth_audit` table. Take a **full DB snapshot before the
   Alembic revision runs** — this is the rollback path (no `users.legacy_role`
   column; see §5.2 hard rule 2). Alembic migration (Phase 2a introduces
   Alembic; today there is none — schema is `init_db` + ad-hoc `_migrate()`
   in `db.py`).
2. **Persona migration** (§5.2): split existing `users.role` → `persona` + `roles`
   using the rules table; **`QuizManager` → `{learner}`**, never admin; emit a report
   of former-`QuizManager`/`Moderator`/`FeedCreator` emails for review.
3. **Permission layer** (§3): add `core/auth/permissions.py` with `PERMISSIONS` +
   `require_permission`; default roleless users to `learner`; make `platform_admin`
   the single bypass (remove the `QuizManager` bypass at `auth.py:129`). Repoint all
   seven `require_role([...])` call sites (`main.py:515,622,650,682,694,741,756`) to
   `require_permission("…")`. Reassign `/admin/attempts` and `/api/admin/questions`
   to `quiz_admin` semantics; keep `require_role` as a deprecated shim during cutover.
4. **Persona-only onboarding** (§5.1): swap `set_user_role` → `set_user_persona` at
   `main.py:279`; point `home`/`history` reads at `user["persona"]`
   (`main.py:163,172,483`). Update `templates/onboarding_role.html` copy only as
   needed (it is already framed as a recommendation).
5. **Remove dev auto-elevation** (§6.5): delete the `QuizManager` assignment in
   `upsert_user` (`storage.py:74`, `storage.py:84`); dev users get `{learner}`. Add
   `DEV_SEED_ADMINS` handling.
6. **PKCE** (§6.1): add `code_verifier`/`code_challenge` (S256) generation in
   `/auth/google` (`main.py:217-219`), carry `code_verifier` in the token POST
   (`auth.py:67-77`).
7. **ID-token + nonce verification, strict domain** (§6.2–6.3): verify the Google
   `id_token` JWT (JWKS, `iss`/`aud`/`exp`/`nonce`, `email_verified`, `hd`), enforce
   `ALLOWED_DOMAIN` server-side, make empty-domain a startup error in non-dev. Add the
   JWT/JWKS dependency (`google-auth`/`authlib`/`PyJWT`) — none present today.
8. **Session cookie flags** (§6.4): explicit `SessionMiddleware` config —
   `same_site=lax`, `https_only=not DEV_MODE`, `session_cookie` name, `max_age=8h`;
   require env `SECRET_KEY` in prod (remove the hardcoded default, `config.py:22`).
9. **Session / cookie cutover** (force-logout by `SECRET_KEY` rotation —
   **intentional**). When Phase 2b deploys, the new `SessionMiddleware`
   config plus a rotated `SECRET_KEY` invalidates every existing session
   cookie, forcing every user back through the hardened Google flow (§6.1–
   §6.3). This is **deliberate**: it is the cleanest way to flush the
   pre-v2 cookie shape (no `Secure`, no explicit `SameSite`, no `max_age`,
   single `role` field) without writing a legacy reader. Operationally,
   communicate this as a one-time re-login to all users on cutover day.

   The session payload also changes shape: pre-v2 sessions carry
   `user["role"]` (a single string from the dead capability vocabulary);
   v2 sessions carry only `{email, name, picture}` and capability is read
   per-request from `users_service.roles_for(email)` (§3, C-02). Every
   read site of `user.get("role")` in `quiz-certification/app/main.py`
   must be repointed before cutover. The exhaustive list (file:line →
   replacement) is:

   | file:line | current read | v2 replacement |
   |---|---|---|
   | `quiz-certification/app/main.py:90` | `if not user.get("role"):` (in `_require_user_with_role`) | `if not user.get("persona"):` — onboarding-redirect now keys on persona (§5.1). |
   | `quiz-certification/app/main.py:110` | `"role": db_user.get("role"),` (assembled into session dict in `_load_user`) | Drop the `role` key from the session dict. Add `"persona": db_user.get("persona")` for the home/history reads. |
   | `quiz-certification/app/main.py:155` | `if not user.get("role"):` (home route gate) | `if not user.get("persona"):` — persona drives `recommended_level` (§5.1). |
   | `quiz-certification/app/main.py:208` | `if not user.get("role"):` (login-landing gate) | `if not user.get("persona"):`. |
   | `quiz-certification/app/main.py:243` | `if not user.get("role"):` (onboarding-redirect helper) | `if not user.get("persona"):`. |
   | `quiz-certification/app/main.py:262` | `current_role=user.get("role"),` (onboarding template kwarg) | `current_persona=user.get("persona"),`. |
   | `quiz-certification/app/main.py:275` | `current_role=user.get("role"),` (onboarding error re-render) | `current_persona=user.get("persona"),`. |
   | `quiz-certification/app/main.py:290` | `current_role=user.get("role"),` (onboarding success re-render) | `current_persona=user.get("persona"),`. |
   | `quiz-certification/app/main.py:311` | `if not user.get("role"):` (`/quiz/start` gate) | `if not user.get("persona"):`. |
   | `quiz-certification/app/main.py:452` | `if not user.get("role"):` (`/quiz/take` gate) | `if not user.get("persona"):`. |

   And the one `auth.py` site that backs the capability check:

   | file:line | current read | v2 replacement |
   |---|---|---|
   | `quiz-certification/app/auth.py:126` | `user_role = db_user.get("role") or "User"` (and the `if user_role == "QuizManager"` bypass at `auth.py:129`, plus the `user_role in allowed_roles` check at `auth.py:132`) | Entire `require_role` body is replaced by `require_permission` (§3) reading `users_service.roles_for(u["email"])` — the helper from C-02. Old `require_role` becomes a deprecated shim that delegates. |

   Templates that render `current_role` (`templates/onboarding_role.html`)
   rename to `current_persona` in the same commit. No template still reads
   a capability string post-cutover; capability is server-side only.
10. **Role-assignment API + seed + audit** (§7): `POST /api/admin/roles`
    (`require_permission("role.assign")`); `ADMIN_EMAILS` startup/login seeding of
    `platform_admin`; `auth_audit` writes; Directus-side mirroring hook (full Directus
    wiring is Phase 4, but the seam + mirror contract is defined here).
11. **Two-plane sync contract** (§4.3): document/implement the email-keyed mirror
    from Directus role membership into the FastAPI-side `user_roles` table so
    FastAPI and Directus never disagree; the mirror is one-way (§7.2);
    `modules/cms/` remains auth-free (read/webhook only).

**Cross-doc dependencies:** schema rows + Alembic → `v2/03-data-model.md`; `ADMIN_EMAILS`,
`SECRET_KEY`/secrets policy, JWT dependency, Directus Google-SSO env → `v2/05-config-cms.md`;
the Secure-cookie/PKCE/JWT items also feed the security checklist in
`v2/07-security-baseline.md`. The default taxonomy (§2.1), the unified-RBAC flip
(§2.3), and the anonymous-access micro-decisions (matrix rows 6, 12, 13, 16) are the
**Phase 0 gate decisions** for this doc.
