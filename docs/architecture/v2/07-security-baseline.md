# v2/07 · Security baseline — threat model, findings, headers, hardening

> Status: **Phase 0 — DESIGN ONLY.** No code changes. This is the single
> authoritative security checklist for v2. Every audit finding gets a row
> in §2 with severity, remediation, and the phase that owns the fix.
>
> Owner agent: Security. Covers plan item **7** (security baseline)
> and **9** (cert dev-mode design). Coordinates with:
> - `01-blueprint.md` §3 — `core/security.py:install_middleware()` is where
>   §3-§4 here are *implemented*.
> - `03-data-model.md` §2.5 — `signing_keys` table; §9 here owns the cert
>   dev-mode design that uses it.
> - `04-authz-model.md` §6 — PKCE / nonce / cookies / domain enforcement.
>   This doc reproduces the same requirements as security findings rather
>   than re-deriving them.
> - `05-config-cms.md` (forthcoming) — env layout, Directus secrets, the
>   `ADMIN_EMAILS` / `SECRET_KEY` startup contract.
> - `06-caching-performance.md` (forthcoming) — Apache header config; §3
>   here owns the header *set*, §6 owns where the directives are written.
>
> All file:line citations are against branch `v2` (forked from `main`) at
> the time of writing.

---

## 0 · Scan box

- The platform's secrets and session posture today rest on **two
  in-source defaults** (`config.py:22`, `config.py:59`) that silently
  ship as the real keys if an operator forgets to override env. v2
  must **fail-closed**: empty `SECRET_KEY`/`APP_PAYLOAD_SECRET` in
  non-dev = startup error.
- The `SessionMiddleware` mount (`main.py:61`) has **no explicit cookie
  policy** — Starlette's defaults give `HttpOnly` but **not** `Secure`,
  **not** `SameSite=Lax`, and **no `max_age`** (browser-session
  cookies). The `CORSMiddleware` mount (`main.py:54-60`) allows
  credentials with `methods=["*"]`, `headers=["*"]` and **hardcoded
  `localhost` origins shipped in production code**. Both fixes are
  one block in `core/security.py:install_middleware()` (cross-ref 01 §3).
- The Apache vhost (`deploy.sh:879-922`) ships **TLS 1.2/1.3 + HSTS**
  (good) but **no CSP, no `X-Content-Type-Options`, no
  `X-Frame-Options`, no `Referrer-Policy`, no `Permissions-Policy`,
  no COOP/CORP**. §3 below specifies the exact header set; §6 (the
  caching/perf doc) owns the Apache `Header always set …` lines.
- **Two media endpoints are anonymous today** —
  `/media/video/{asset_id}` (`main.py:812`) and
  `/media/image/{asset_id}` (`main.py:850`). v2 treats this as a
  conscious decision (feed reads are also anonymous per `04` matrix
  row 6), but the design must record it explicitly and add path-only
  obscurity (random UUID, no listing) + Range-cap + Postgres-side LO
  read scoping. See §7.4.
- **Cert dev-mode (item 9)** is the highest-risk legacy debt. Today
  dev and prod use the same HMAC key (whatever `SECRET_KEY` happens
  to be), same `CCA-F-` prefix, same PDF template, so a `DEV_MODE=true`
  install can mint certs indistinguishable from real ones. §9 below
  defines the full per-environment scheme using the `signing_keys`
  table from `03 §2.5`, a `DEV-` cert-ID namespace, a PDF watermark,
  and a public verifier that flags non-production certs.
- **Findings table:** 28 rows across auth, session, headers, CORS,
  CSP, secrets, db, oauth, upload, xss, csrf, cert, encryption,
  network, process, supply-chain. §10 indexes them by owning phase
  so each later phase has its security checklist.

---

## 1 · Threat model (one page)

### 1.1 Actors

| Actor | Authenticated as | Capability surface |
|---|---|---|
| **Anonymous** | none | read public verify (`/verify/{cert_id}`), course content (`/anatomy/*`), SPA shell (`/app/*`), feed reads, media GETs |
| **Learner** | Google SSO (or dev email) → FastAPI session | quiz start/submit, own attempts, certs, role/persona edit |
| **Feed Contributor** | Learner + `feed_contributor` role | POST feed (`/api/feed`), media upload (`/api/media/upload`) |
| **Feed Moderator** | Staff plane (Directus + `feed_moderator`) | moderate queue (`/api/moderate/*`), flag/remove |
| **Content Author** | Staff plane (Directus only) | edit chapters/frameworks/quiz bank via CMS |
| **Quiz Admin** | Staff plane (capability) | publish questions (`/api/admin/questions`), see attempts (`/admin/attempts`) |
| **Platform Admin** | Staff plane + `platform_admin` | role grants, signing-key rotation, infra |
| **External attacker** | none | network, OAuth callback, file uploads, XSS, CSRF, replay, supply-chain |
| **Insider (privilege creep)** | any role | abuse of role bypass, dev-mode toggle, dev cert minting |

Roles per `04-authz-model.md §2.1` (default taxonomy). The
`role.assign` permission is owned by Platform Admin only (`04 §3`).

### 1.2 Assets

| Asset | Where it lives today | Confidentiality | Integrity | Availability |
|---|---|---|---|---|
| User identity (email, name, picture) | `users` table (Postgres) | medium | high | medium |
| Quiz attempts + scores | `attempts.payload` (jsonb) + `attempts.signature` | medium | **critical** | high |
| Certificates (issued PDFs + IDs) | `certificates/*.pdf` on disk, `attempts.cert_id` | low (publicly verifiable) | **critical** | high |
| Cert HMAC key (`SECRET_KEY`) | env var → `config.py:22` (default!) | **critical** | **critical** | n/a |
| AES-GCM payload key (`APP_PAYLOAD_SECRET`) | env var → `config.py:59` (default!) | high | high | n/a |
| Session secret (same `SECRET_KEY`) | env → `SessionMiddleware` (`main.py:61`) | **critical** | high | n/a |
| OAuth client secret (`GOOGLE_CLIENT_SECRET`) | env → `auth.py:72` | **critical** | high | n/a |
| Media bytes (pg large objects) | `pg_largeobject` (OID indirection from `media_assets`) | medium | high | medium |
| Question bank (correct answers) | `questions` table | **high** (would invalidate quiz) | **critical** | high |
| User-generated content (feed) | `feed_items.data` (jsonb) | low | high | medium |
| Source code + history | git working tree + remote | low | high | high |
| Postgres credentials (`DATABASE_URL`) | `.env` on VM (0600) | **critical** | **critical** | n/a |
| `.env` itself (all secrets) | `/opt/dept-anatomy/quiz-certification/.env` (0600, owner `cca:cca`) | **critical** | **critical** | n/a |

`.env` is **gitignored** (`.gitignore` line for `.env`) and not in git
history — verified by `git ls-files | grep .env` returning only the two
`*.example` files. The hazard is the **in-source defaults** that the
deployed app falls back to when an operator forgets, not a leaked file.

### 1.3 Trust boundaries

```
[ Browser ]──TLS 1.2/1.3──→[ Apache 80/443 ]──ProxyPass──→[ uvicorn 127.0.0.1:8000 ]──→[ Postgres /var/run/postgresql ]
                                                                                          ↑
                                                              [ Directus :8055 (Phase 4) ]┘
```

Five boundaries:

1. **Public ↔ Apache** — TLS terminates here. Only ports 80/443
   externally; 80 redirects to 443 when certs exist (`deploy.sh:838-843`).
2. **Apache ↔ uvicorn** — `127.0.0.1:8000` over plain HTTP loopback
   (`deploy.sh:761-766`). Apache sets `X-Forwarded-Proto`
   (`deploy.sh:868, 911`); FastAPI is launched with
   `--proxy-headers --forwarded-allow-ips='*'` (`deploy.sh:765-766`).
3. **uvicorn ↔ Postgres** — Unix socket for the admin path
   (`deploy.sh:411-425`, `PGHOST=/var/run/postgresql`), TCP `127.0.0.1`
   with md5 password auth for the app role (`deploy.sh:685-687`,
   `deploy.sh:721-734`).
4. **Learner plane ↔ Staff plane** — see `04 §4`. Same Postgres, but
   only Directus (Phase 4) writes content tables; only FastAPI writes
   `attempts`/`quiz_sessions`/`feed_items`. **Plane that receives the
   request enforces it** (`04 §4.4`).
5. **App ↔ external Google / SMTP / CDN** — outbound TLS only.
   `cdn.jsdelivr.net` (mermaid), `fonts.googleapis.com`,
   `esm.sh` (Ajv), `www.deptagency.com` (logo) — all need to land in
   the CSP allow-list (§3.2).

### 1.4 Threats considered

| # | Threat | Primary mitigation | Finding |
|---|---|---|---|
| T1 | Session hijack via XSS or network | Secure/HttpOnly/SameSite cookies + CSP + TLS | F-COO-01, F-XSS-01, F-CSP-01 |
| T2 | OAuth code interception (no PKCE) | PKCE S256 on `/auth/google` | F-OAU-01 |
| T3 | Forged cert / signature replay | Per-env signing keys + visible env marker | F-CER-01, F-CER-02 |
| T4 | Privilege escalation via dev auto-elevation | Remove `QuizManager` upsert branch | F-AUT-02 |
| T5 | Multi-worker quiz desync / replay | Move `_active_quizzes` to `quiz_sessions` table | F-SES-02 |
| T6 | Anonymous media enumeration / DoS | UUID-only handles, Range cap, rate limit | F-MED-01 |
| T7 | Malicious upload (MIME spoof, polyglot, ZipSlip) | Multi-offset sniff + ffprobe + UUID rename + SVG deny | F-UPL-01..04 |
| T8 | XSS in feed renderer | `esc()`-only data fields, `raw()` reserved for course content | F-XSS-01 |
| T9 | CSRF on state-changing GETs | `SameSite=Lax`, audit GETs that mutate | F-CSR-01 |
| T10 | Cleartext secret in source default | Fail-closed startup, env-only | F-SEC-01..03 |
| T11 | Supply-chain (unpinned `fastapi`/`uvicorn`/CDN drift) | Pin requirements + SRI on CDN scripts | F-SUP-01, F-SUP-02 |
| T12 | Insider role abuse | `auth_audit` table + `role.assign` perm + signed audit | F-AUD-01 (cross-ref `04 §7.4`) |
| T13 | Process compromise (broken Python dep) | systemd hardening, app user nologin | F-PRO-01..02 |
| T14 | TLS expiry / manual cert handling | certbot automation | F-NET-02 |

Out of scope for v2 (parked for v3): DDoS scrubbing, WAF, customer
PII export tooling, FIDO2/WebAuthn, mTLS for staff plane.

---

## 2 · Findings table (the single source of truth)

One row per finding. ID format: `F-<area>-<n>`. Severity: **critical**
(must fix before any prod), **high** (fix during phase), **medium**
(fix before Phase 5b), **low** (track, fix opportunistically).

| ID | Area | Sev | Evidence (file:line) | Finding | Remediation | Owning phase |
|---|---|---|---|---|---|---|
| **F-SEC-01** | secrets | critical | `quiz-certification/app/config.py:22` | `SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-CHANGE-IN-PROD-7f8a9b0c1d2e3f4a")` — in-source default ships as the real session + HMAC key if env is unset. | Remove default; in `core/config.py` raise `RuntimeError` on startup when `DEV_MODE=false` and `SECRET_KEY` is empty or the literal dev marker. Generate via `secrets.token_urlsafe(32)`; `deploy.sh:536-538` already does this for fresh installs — make it mandatory. | **Phase 2e** (secrets boundary, cross-ref 05) + **Phase 1** (fail-closed startup check lands with the `core/config.py` move per `01 §6.1`). |
| **F-SEC-02** | secrets | critical | `quiz-certification/app/config.py:59` | `APP_PAYLOAD_SECRET = os.getenv("APP_PAYLOAD_SECRET", "dev-payload-secret-32bytes-long!")` — AES-GCM key default ships. The string is SHA-256'd at `encryption.py:18` so the *derived* key is deterministic from a known input. | Same fail-closed rule; in prod, require explicit env. Add a self-test on startup that derives the key and refuses to start if it matches the SHA-256 of the dev marker. Document key rotation (§5.2). | **Phase 2e** + **Phase 1** |
| **F-SEC-03** | secrets | high | `quiz-certification/.env` (on disk, **not** in git per `.gitignore` + `git ls-files` check) | Local dev `.env` carries `SECRET_KEY=dev-secret-CHANGE-IN-PROD-7f8a9b0c1d2e3f4a` (same string as the in-source default). Not committed, but trivially exfiltrated from any laptop image and the operator habit normalises a weak literal. | Replace local `.env` `SECRET_KEY` with a generated value on cutover. Add a `make dev-setup` target / `start_local.sh` precheck that refuses the literal dev marker. Add a `gitleaks` pre-commit hook to catch any future drift (§5.3). | **Phase 1** (dev tooling) |
| **F-SES-01** | session | critical | `main.py:61` | `app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)` — no `https_only`, no `same_site`, no `max_age`, no `session_cookie` name; defaults give a browser-session cookie without `Secure` over HTTPS. | Exact config in §4. `core/security.py:install_middleware()` sets `https_only=not DEV_MODE`, `same_site="lax"`, `max_age=8*3600` (Q-1 default), `session_cookie="cca_session"`. | **Phase 2e** (security middleware seam, `01 §3` plan) — cross-ref `04 §6.4` and §8 (session/cookie cutover step). |
| **F-SES-02** | session | high | `main.py:69` (`_active_quizzes: Dict[str, Dict] = {}`), used `main.py:327, 367-372, 415` | Active quizzes held in process memory. With `QUIZ_WORKERS=2` (`deploy.sh:42`) a quiz started on worker A and submitted to worker B is `quiz_not_found`. Worse: any worker restart drops in-flight quizzes; an attacker who can recycle a worker mid-quiz forces re-issue and may extend the window. | Move to `quiz_sessions` table (Postgres) per `03 §2.4`. Adds a hard server-side window (start ts + duration), prevents replay across the window, scales to N workers. | **Phase 2a** (table) + **Phase 2c** (quiz module routes use it) — cross-ref `03 §3 step 5`. |
| **F-COO-01** | cookies | critical | `main.py:61` (same site as F-SES-01) | No `Secure` flag means the session cookie can be sent over HTTP if a downgrade occurs (HSTS mitigates, but only after first visit). | `https_only=True` whenever `DEV_MODE=false`. HSTS already on (`deploy.sh:893`); preload candidacy noted in §3.1. | **Phase 2e** |
| **F-COR-01** | cors | high | `main.py:54-60` | `allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"]` hardcoded **in production code**; `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=True`. The 8080 origins are leftover from the dev SPA; production serves the SPA same-origin via Apache `Alias /app` (`deploy.sh:902-908`). | In `core/security.py`: origins from `CORS_ORIGINS` env (comma-sep, empty = no `CORSMiddleware` at all). Production = no origins (same-origin only). Dev = the localhost set. Restrict `allow_methods=["GET","POST"]`; `allow_headers=["Content-Type","X-Encrypt-Payload"]`. | **Phase 2e** |
| **F-CSP-01** | headers | high | `deploy.sh:879-922` — only `Strict-Transport-Security` is set | No CSP. The course HTML loads mermaid from `cdn.jsdelivr.net` (`content-system/anatomy-of-code-course.html:525`); the SPA loads Ajv from `esm.sh` (`app/js/feed/validate.js:25-26`); fonts from `fonts.googleapis.com` (`app/index.html:7-9`); logo from `www.deptagency.com` (`content-system/anatomy-of-code-course.html:683`). The DEPT logo URL hardcoded across files. | Add the full header set in §3. CSP allow-list narrowed to the four CDNs above; `'self'` for everything else; `'unsafe-inline'` for `<style>` only (mermaid injects styles); **no `'unsafe-eval'`**. SRI hashes on the three CDN scripts (mermaid, Ajv, ajv-formats). | **Phase 3c** (Apache headers, `06`-owned) — this doc defines the *set*; `06-caching-performance.md` writes the `Header always set` directives so they live next to cache headers. |
| **F-HDR-01** | headers | medium | `deploy.sh:879-922` | Missing: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`. | Add per §3. | **Phase 3c** |
| **F-OAU-01** | oauth | high | `auth.py:43-54, 67-77`; `main.py:217-219` | Google OAuth code flow has **no PKCE**. Confidential-client flow, but PKCE is now best practice and required for some Google client types; it also defends against an attacker who steals the auth code from the redirect URI's referrer or proxy logs. | Generate `code_verifier` (`secrets.token_urlsafe(64)`) on `/auth/google`, store in session, send `code_challenge` (S256) to Google, replay on token POST. Spec'd fully in `04 §6.1`. | **Phase 2b** (cross-ref `04 §8 step 6`) |
| **F-OAU-02** | oauth | high | `auth.py:18-25` (`is_allowed_email`) | Domain check **fails open** on empty `ALLOWED_DOMAIN`: `if not allowed: return True`. A misconfigured env (`ALLOWED_DOMAIN=`) admits any verified Google account. | In `core/config.py`: when `DEV_MODE=false`, require `ALLOWED_DOMAIN` non-empty and refuse to start. Also verify the Google `id_token` `hd` claim server-side after PKCE (cross-ref `04 §6.2`). | **Phase 2b** + **Phase 1** |
| **F-OAU-03** | oauth | medium | `auth.py:57-98` | No ID-token JWT verification — the app trusts the userinfo endpoint response after a bare access-token exchange. No `nonce`, no `iss`/`aud`/`exp`/`email_verified` checks. | Add `google-auth` (or `authlib`) dependency; verify the ID token JWKS, fields, and `nonce` matched. Specified in `04 §6.3`. | **Phase 2b** |
| **F-AUT-01** | authz | high | `auth.py:128-130` | `if user_role == "QuizManager": return db_user` — QuizManager bypasses every role check. Combined with F-AUT-02, every dev user is admin. | Remove the bypass; only `platform_admin` bypasses (cross-ref `04 §3`). Repoint the seven `require_role` call sites (`main.py:515,622,650,682,694,741,756`) to `require_permission()`. | **Phase 2b** (cross-ref `04 §8 step 3`) |
| **F-AUT-02** | authz | critical | `storage.py:74, 84` | `upsert_user`: `if config.DEV_MODE: role = "QuizManager"`. Combined with F-AUT-01 every dev signup is admin and (because the dev secret is also the prod default, F-SEC-01) a misconfigured prod becomes the same. | Delete both `QuizManager` assignments (`04 §8 step 5`). Dev users get `{learner}`. `ADMIN_EMAILS` env seeds the first `platform_admin` on first login. | **Phase 2b** |
| **F-CER-01** | cert | critical | `certificate.py:34-160` + `storage.py:21-28` | Dev and prod use **the same HMAC key** (whatever `SECRET_KEY` is), the same `CCA-F-YYYYMMDD-XXXXXXXX` prefix (`main.py:378-383`), and **the same PDF template** with no environment indication. A `DEV_MODE=true` install can issue certificates the public `/verify` page validates identically to real ones. | Per-environment signing via `signing_keys` table (cross-ref `03 §2.5`) — full design in §8 below. DEV certs get `DEV-` cert-ID prefix, a "DEVELOPMENT — NOT VALID" watermark, a different footer line, and the verifier badges them. Real certs verify byte-identical (production environment, legacy key carried forward). | **Phase 2a** (table) + **Phase 2c** (certificate code) — cross-ref `03 §3 step 4`. |
| **F-CER-02** | cert | high | `main.py:488-503` (public verify) | Verifier returns `valid` = bool only. After F-CER-01 lands it must also return `environment` and badge dev/staging certs distinctly in the UI. | New verifier contract per §8 — adds `environment`, `signing_key_id`, `key_active` (rotated keys still verify via `can_verify`). | **Phase 2c** |
| **F-CER-03** | cert | medium | `certificate.py:32-46` (no signature recorded inside the PDF itself) | The HMAC lives in `attempts.signature` (Postgres). A regenerated PDF (`main.py:471-475`) is recreated from record + key on demand. Acceptable, but the verify URL on the PDF (`certificate.py:146`) points at the bare domain `dept.academy/verify/{cert_id}` — verify by ID only, which is fine, but recommend QR code with the full HTTPS URL for friction-free verification. | Add QR code (reportlab supports it) in §8 design. | **Phase 2c** (nice-to-have; not blocking) |
| **F-ENC-01** | encryption | low | `encryption.py:17-18` | `_STATIC_KEY` derived once at module import from `APP_PAYLOAD_SECRET` — fine for AES-GCM with random nonces, but rotation requires a process restart. `_decrypt_request_payload` (`main.py:117-124`) silently falls back to plaintext if `nonce`/`ciphertext` missing — confusing in logs but not a vuln. | Document the rotation procedure (§5.2). Add a startup log line stamping the key fingerprint (first 8 hex of SHA-256 of the key) so ops can tell when it actually changes. | **Phase 2e** |
| **F-UPL-01** | upload | high | `media_service.py:32-49` | `detect_mime_type` checks signatures at **offset 0** only (with one special case for `ftyp` at 4–12). Polyglot files (e.g. JPEG header + ZIP body) pass. The dispatcher trusts the result for size-cap selection (`main.py:768-769`). | Multi-offset sniff: re-check at 8, 16, 32; reject if any offset disagrees with the chosen MIME class. Also: verify the file is actually parseable by Pillow / ffprobe before storage (already partly done at `media_service.py:52-83`); reject any container claim the parser disagrees with. | **Phase 2d** (media module hardening) |
| **F-UPL-02** | upload | high | `main.py:760-786` | Size cap is enforced **after** the first 2048 bytes are already read (`head_bytes = await file.read(2048)`), then again during stream write. The pre-read leaks resource use; an attacker spamming 0-byte multiparts can still cost the validator. Plus, no per-IP / per-user rate limiting on `/api/media/upload`. | Enforce `Content-Length` from headers up front; reject `> max_size` before reading any body bytes; add `slowapi`-style rate limit (or Apache `mod_ratelimit`/`mod_qos`) at 5 uploads / minute / user. | **Phase 2d** + **Phase 3c** (Apache rate limit) |
| **F-UPL-03** | upload | medium | `media_service.py:25-30` | No SVG entry in `_SIGNATURES`, which is correct (SVG is denied today). Make this explicit: **never** add SVG to the allow-list; SVG can carry inline `<script>`. If a future requirement appears, sanitize via `bleach`-style allow-list, never raw. | Add a code comment + a test that explicitly asserts SVG upload returns 400. | **Phase 2d** |
| **F-UPL-04** | upload | medium | `media_service.py:86-130` (`store_media_asset`) | Filename is preserved in metadata (`asset.filename = filename`) but not in URLs (URLs use `asset_id` UUID — good, `media_service.py:110`). When the file is served, no `Content-Disposition` is set (`main.py:822-827, 850-862`). Browsers will sniff the displayed name from the URL (the UUID — safe), so impact is low; explicit `Content-Disposition: inline; filename="<sanitised>"` is still recommended for downloads, and `Content-Type-Options: nosniff` (§3) covers the rest. | Add `Content-Disposition` headers in `modules/media/routes.py`; sanitise the stored filename (strip path separators, limit to 64 chars, ASCII-fold). | **Phase 2d** |
| **F-MED-01** | upload | medium | `main.py:812, 850` | `/media/video/{asset_id}` and `/media/image/{asset_id}` are anonymous — anyone with the UUID can stream. This is **intentional** for feed media (anonymous read per `04 §3` row 6), but should be documented and bounded: (a) UUIDv4 only (`media_service.py:110` — confirmed); (b) cap Range responses to `MAX_VIDEO_SIZE_MB`; (c) reject `Range` requests on images (currently the image path uses `stream_video_chunks` for the whole blob — works but should set a hard size cap); (d) rate limit egress per IP. | Document explicitly in `modules/media/routes.py`; add Range-cap; add per-IP egress rate limit at Apache (`mod_qos` or `mod_ratelimit`). | **Phase 2d** + **Phase 3c** |
| **F-XSS-01** | xss | medium | `app/js/feed/list.js`, `card.js`, `post.js`, `scenario.js` etc.; helpers at `app/js/util/dom.js:4-9` | Feed renderers consistently use `esc()` for every user-supplied field — confirmed by `grep -n raw\(` over `app/js/feed/` returning **zero** matches and `app/js/modes/feed.js:126-235` showing `esc()` on every interpolation. **However:** `app/js/blocks/*` (course chapter renderers) use `raw()` for `html`, `q`, `c` fields (`callout.js:16`, `cardgrid.js:10-11`, `map.js:9-10`, `prose.js:3`, etc.). That is **correct today** because chapter content comes from `course_chapters` (Postgres, write-restricted to Content Author in v2 per `04 §3`). | Add a renderer convention test (`tests/baseline/test_xss.py`) that asserts: (a) every `app/js/feed/*` file referencing a user field uses `esc()`, never `raw()`; (b) `raw()` is only imported by `app/js/blocks/*` and `modes/{scroll,read}.js`. Add a CSP `script-src` that blocks inline `onclick` (`app/index.html:40` uses `onclick="toggleAppTheme()"` — refactor to `addEventListener`). | **Phase 1** (FE reorg per v2-plan taxonomy) + **Phase 5b** (acceptance) |
| **F-XSS-02** | xss | low | `app/index.html:40` | Inline `onclick="toggleAppTheme()"` violates a strict CSP `script-src 'self'`. | Remove the inline handler; bind in `app/js/main.js` via `addEventListener`. | **Phase 1** (FE reorg) |
| **F-CSR-01** | csrf | medium | All POST routes today rely on session cookies; `SessionMiddleware` default has no `SameSite`. State-changing **GETs**: `/logout` (`main.py:248`) is a GET that clears the session — exploitable for forced logout via `<img src>` from any site. Other GETs (`/`, `/login`, `/verify/{id}`) are pure reads. | (a) Set `SameSite=Lax` on the session cookie — covers most CSRF for the POST routes (Lax does **not** carry the cookie on cross-site POST). (b) Convert `/logout` to POST with a CSRF token, or accept the minor forced-logout DoS risk and document. (c) For the cross-plane Directus admin actions, rely on Directus's own CSRF protection. | **Phase 2e** + **Phase 2b** |
| **F-NET-01** | network | medium | `deploy.sh:879-891` | TLS 1.2/1.3 + `SSLCipherSuite HIGH:!aNULL:!MD5` is OK but generic. No explicit modern cipher ordering; `SSLHonorCipherOrder on` defers to OpenSSL defaults. | Tighten to Mozilla "intermediate" 2025 set: `SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384` and explicit `SSLOpenSSLConfCmd Curves X25519:secp256r1:secp384r1`. | **Phase 3c** (Apache vhost lives in `infra/deploy.sh` per `01 §6.4`) |
| **F-NET-02** | network | medium | `deploy.sh:1008-1011` | TLS is provisioned manually; on cert expiry the operator must rerun the script. Cert renewal is therefore an ops liability. | Wire `certbot --apache -d $DOMAIN` into `deploy.sh` Step 9 when `CERT_FILE` is not set and the domain is publicly resolvable. Add a systemd timer (`certbot.timer`) check. | **Phase 3c** (infra) |
| **F-NET-03** | network | high | `deploy.sh:617-635` | Postgres `listen_addresses` is set to `localhost` (good — TCP only on loopback). `pg_hba.conf` is amended with `host ${DB_NAME} ${DB_USER} 127.0.0.1/32 md5` (`deploy.sh:685-687`) — also good. Verify in v2 docs that **no `host all all 0.0.0.0/0`** rule exists by accident. | Add a `deploy.sh` post-condition assertion: `pg_exec` `psql -c "SHOW listen_addresses"` must equal `localhost` or `127.0.0.1`; pg_hba.conf grep must NOT contain `0.0.0.0/0` or `::/0`. Fail the deploy if violated. | **Phase 3c** (infra) |
| **F-PRO-01** | process | high | `deploy.sh:769-773` | systemd unit hardening present: `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=full`, `ReadWritePaths=${QUIZ_DIR}`. **Missing:** `ProtectHome=true`, `ProtectKernelTunables=true`, `ProtectKernelModules=true`, `ProtectControlGroups=true`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `RestrictNamespaces=true`, `LockPersonality=true`, `MemoryDenyWriteExecute=true`, `SystemCallFilter=@system-service`, `SystemCallArchitectures=native`. | Add the above to the systemd unit template in `infra/deploy.sh`. At v2 launch ship `SystemCallFilter=@system-service` **only** (per C-64); the aggressive `~@resources` deny-list is gated on a 24h soak in Phase 3c to avoid Pillow/ffprobe regressions. | **Phase 3c** (v2 launch defaults) + **Phase 3c** (24h soak gating the aggressive filter — C-64) |
| **F-PRO-02** | process | medium | `deploy.sh:467-475` | `cca` user created with `--system --shell /sbin/nologin` — good. No `CapabilityBoundingSet` or `AmbientCapabilities=` in the unit — fine since uvicorn binds 8000 (>1024) and needs none, but document that **no cap is required** and lock it to empty: `CapabilityBoundingSet=` (empty). | One-liner addition in `deploy.sh`. | **Phase 3c** |
| **F-SUP-01** | supply-chain | medium | `quiz-certification/requirements.txt:1-2` | `fastapi` and `uvicorn[standard]` are **unpinned**; the other 11 packages are pinned. A new `fastapi` release could change middleware semantics silently. | Pin every line. Generate `requirements.lock` via `pip-compile` (pip-tools) and commit. Add Dependabot or `pip-audit` to CI. | **Phase 1** (toolchain) + ongoing |
| **F-SUP-02** | supply-chain | medium | `content-system/anatomy-of-code-course.html:525`, `app/js/feed/validate.js:25-26` | Three CDN-hosted scripts: mermaid (`cdn.jsdelivr.net`), Ajv (`esm.sh`), ajv-formats (`esm.sh`). No SRI; if jsdelivr/esm.sh is compromised or returns a different artefact, the page executes whatever they serve. | Add `integrity="sha384-…"` + `crossorigin="anonymous"` for the three. esm.sh's pinned version URLs (`@8.17.1`, `@3.0.1`) are stable; jsdelivr at `@11` floats — pin to `@11.x.x` exact. Add CSP `script-src` to the same three origins only. | **Phase 3c** (FE security headers + SRI both land with Apache headers) |
| **F-AUD-01** | audit | high | No `auth_audit` table exists today | No record of who granted which role to whom, who flagged what, who rotated which key. Insider abuse is invisible. | `auth_audit` table from `04 §7.4`; write rows on every role grant/revoke, every moderator action (`/api/moderate/action`, `main.py:693-724`), every cert revocation, every signing-key rotation. The CMS plane mirrors to the same table via Directus event hooks. | **Phase 2a** (table) + **Phase 2b** (writes) — cross-ref `04 §8 step 9`. |
| **F-BAK-01** | ops | medium | None today | No documented backup of Postgres (which now holds attempts, certs, media bytes, feed UGC, course content). | `pg_dump` nightly + `pg_basebackup` weekly to a separate volume; offsite encrypted (age/gpg) once. Media large objects are included in `pg_dump --large-objects`. Retention 90 days. Spec'd in §9.4. | **Phase 3c** (infra) |

**28 findings total** (4 critical, 9 high, 13 medium, 2 low). Counted
by row.

---

## 3 · Headers — the concrete set

This is the **definitive header set** for v2 production. The directives
are written in Apache vhost by `06-caching-performance.md` (which owns
the file); this doc owns the *values*. Where a directive duplicates
something in 06, **06 wins** — that doc is the single Apache file.

### 3.1 Always-on headers (HTTPS vhost)

```apache
# TLS (already in deploy.sh:893 — keep, extend per F-NET-01)
Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"

# Anti-sniff / clickjacking / referrer leak
Header always set X-Content-Type-Options "nosniff"
Header always set X-Frame-Options "DENY"
Header always set Referrer-Policy "strict-origin-when-cross-origin"

# Browser-feature lock-down — explicitly deny everything we don't use
Header always set Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=(), interest-cohort=()"

# Process isolation
Header always set Cross-Origin-Opener-Policy "same-origin"
Header always set Cross-Origin-Resource-Policy "same-origin"
# COEP intentionally omitted — would block the four CDN scripts; revisit when
# we self-host mermaid/Ajv/fonts (item parked for v2.1).
# Note: `COOP: same-origin` is compatible with the current top-level OAuth
# redirect flow. If PKCE work in `04 §6.1` ever switches to a popup/postMessage
# flow, COOP must be relaxed to `same-origin-allow-popups` — tracked as a
# Phase 2b regression check (see §11.1 item 17) per C-33.
```

`preload` on HSTS commits to TLS forever; only flip on after a 30-day
soak with the non-preload variant.

### 3.2 Content Security Policy

CSP applies to all HTML responses from the FastAPI proxy and the two
`Alias` static mounts. Two profiles — the SPA and the course HTML
have different CDN needs.

**For `/` (FastAPI templates) and `/app/*` (SPA):**

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self' https://esm.sh;
  style-src  'self' 'unsafe-inline' https://fonts.googleapis.com;
  font-src   'self' https://fonts.gstatic.com;
  img-src    'self' data: blob: https://www.deptagency.com;
  media-src  'self' blob:;
  connect-src 'self' https://esm.sh;
  frame-ancestors 'none';
  form-action 'self';
  base-uri   'self';
  object-src 'none';
  upgrade-insecure-requests;
  report-to csp-endpoint

Report-To: {"group":"csp-endpoint","max_age":10886400,"endpoints":[{"url":"/csp/report"}]}
```

**For `/anatomy/*` (course HTML — needs mermaid and `<video>`):**

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self' https://cdn.jsdelivr.net;
  style-src  'self' 'unsafe-inline' https://fonts.googleapis.com;
  font-src   'self' https://fonts.gstatic.com;
  img-src    'self' data: blob: https://www.deptagency.com;
  media-src  'self';
  connect-src 'self';
  frame-ancestors 'none';
  form-action 'self';
  base-uri   'self';
  object-src 'none';
  upgrade-insecure-requests;
  report-to csp-endpoint

Report-To: {"group":"csp-endpoint","max_age":10886400,"endpoints":[{"url":"/csp/report"}]}
```

Notes:

- `'unsafe-inline'` for **styles only** (mermaid injects inline
  styles; SPA has none — keep parity for now, tighten to nonce-based
  later).
- **No `'unsafe-eval'`** — Ajv 2020 in standalone build doesn't need
  it; mermaid 11 doesn't need it. Verify on Phase 5b regression.
- `media-src 'self'` on the course profile covers the `<video>` tags in
  `/anatomy/*` (framework-explainer media served from `/media/video/…`).
- **Reporting:** `report-to csp-endpoint` (modern; `report-uri` is
  deprecated). Endpoint `modules/security/routes.py:csp_report` ingests
  the JSON body and writes to **file/journald** (`/var/log/cca/csp.log`
  via stdlib `logging` → systemd journal). **No DB table.** A
  `security_audit` table is **deferred to v2.1**; for v2 we never write
  CSP reports to Postgres. Cross-ref §10 and the C-31 entry in `00`.
- Phase 3c implements two `<LocationMatch>` blocks in Apache so the
  course HTML and the SPA each get their own CSP + `Report-To` header.

### 3.3 SRI for the three CDN scripts

```html
<script src="https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
        integrity="sha384-<computed at Phase 3c>"
        crossorigin="anonymous"></script>
```

For `esm.sh` (Ajv) — esm.sh returns redirects, so SRI needs the final
artefact URL after a one-shot fetch. Phase 3c computes both hashes and
pins them (alongside the CSP roll-out).

---

## 4 · Session + cookie policy

### 4.1 Exact `SessionMiddleware` config

`core/security.py:install_middleware(app)` mounts:

```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware,
    secret_key      = config.SECRET_KEY,                # fail-closed via core/config
    session_cookie  = "cca_session",                    # named, not the default
    max_age         = 8 * 3600,                         # 8 hours (Q-1 default, security-stronger)
    same_site       = "lax",                            # F-CSR-01, F-COO-01
    https_only      = not config.DEV_MODE,              # F-COO-01
    path            = "/",
    domain          = None,                             # host-only — no subdomain leakage
)
```

Per `04 §6.4` the dev/prod split is (gate decision Q-1 locked `max_age=8h` —
matches `04 §6.4` verbatim):

| Env | `https_only` | `same_site` | `max_age` |
|---|---|---|---|
| `DEV_MODE=true` | `False` | `lax` | 8 hours |
| `DEV_MODE=false` | `True` | `lax` | 8 hours |

`SameSite=strict` rejected because the OAuth callback is a cross-site
top-level navigation; `lax` allows it while still blocking cross-site
POST CSRF.

### 4.2 Session/cookie cutover

The eight `user.get("role")` read sites in `main.py` (enumerated in
`04-authz-model.md §8` — the "session/cookie cutover" step) get
repointed in Phase 2b. Existing dev sessions are force-logged-out by
the `SECRET_KEY` rotation that lands in the same phase (intentional —
see `04 §8`); operators are warned in the cutover runbook. This doc
defers the full step list to `04 §8`; no duplication here.

### 4.3 Session rotation

- New session id on login (`request.session.clear()` then write the
  user dict). Already implicit because the dict is empty on logout;
  Phase 2b makes it explicit (regenerate session id post-auth — see
  `04 §6.4`).
- `payload_key` (the per-session AES key, `main.py:146`) regenerated
  on login (already done at `main.py:205, 240`).

### 4.4 Logout

`/logout` (`main.py:248`) clears the session — but it's a GET. F-CSR-01
escalates this to POST in v2 (or accepts the minor forced-logout risk;
the gate decision is logged in §11 below).

---

## 5 · Secrets handling

### 5.1 The never-in-DB rule

- `SECRET_KEY`, `APP_PAYLOAD_SECRET`, `GOOGLE_CLIENT_SECRET`,
  `SMTP_PASS`, `DATABASE_URL` password — **env only**, never in any
  Postgres column.
- `signing_keys` table (`03 §2.5`) holds **metadata**: `key_id`,
  `environment`, `env_var_name`, `is_active`, `can_verify`,
  `retired_at`. **Never the key material.** The app reads
  `os.getenv(env_var_name)` at sign/verify time. Confirmed by `03 §2.5`
  comment "the table never holds the secret".

### 5.2 Rotation procedure

**`SECRET_KEY` (session + cert HMAC today; cert HMAC becomes
per-signing-key in v2 — see §8):**

1. Generate new: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Add `SECRET_KEY_NEXT=<new>` to `.env`, keep `SECRET_KEY=<old>`.
3. Phase 2e ships a `SessionMiddleware` wrapper that accepts both:
   verify with current, sign with next on every write. After 8 hours
   (one `max_age` cycle, per §4.1), every active session has been re-signed.
4. Swap: `SECRET_KEY=<new>`, drop `SECRET_KEY_NEXT`. Restart.

**`APP_PAYLOAD_SECRET`:**

1. Generate new.
2. Since the static key derives at module import (`encryption.py:18`),
   rotation = restart. Quizzes in flight will fail to decrypt their
   submit (small window). Schedule rotation during a low-traffic hour
   and pre-publish a maintenance window.
3. Phase 2c can move to per-session keys exclusively
   (`request.session["payload_key"]`, `main.py:146`) and drop the
   static fallback — rotation then becomes zero-downtime. Tracked as
   F-ENC-02 (low, parked).

**Cert HMAC keys** — see §8.4 below (per-environment, with
`signing_keys.is_active` + `can_verify` flags handling the cutover).

**Google OAuth client secret:**

1. Mint a new secret in Google Cloud Console.
2. Add as `GOOGLE_CLIENT_SECRET_NEXT`; modify `auth.py` to try
   `_NEXT` first then fall back. Soak 24h.
3. Disable the old in Google Console; remove `_NEXT`.

**DB password:**

1. `ALTER ROLE codecoder WITH PASSWORD '<new>'` (via
   `POSTGRES_SUPERUSER_PASSWORD` path, `deploy.sh:174-192`).
2. Update `DATABASE_URL` in `.env`.
3. Restart `cca-quiz`.

### 5.3 Pre-commit gitleaks

`pre-commit` config (`.pre-commit-config.yaml`) added in Phase 1:

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks
        args: [--baseline-path, .gitleaks-baseline.json]
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: detect-private-key
      - id: check-added-large-files
        args: [--maxkb=2048]
```

Baseline records the **one** known dev secret (`config.py:22, :59`) so
gitleaks fires on **new** secrets but not the existing markers (which
F-SEC-01/02 remove anyway).

### 5.4 What happens to dev `.env` on cutover

- On v2 cutover (Phase 5), the production VM keeps its existing
  `.env` (already 0600, owner `cca:cca`, real `SECRET_KEY` from
  `deploy.sh:536-538` first run).
- The **local developer** `.env` (`quiz-certification/.env`) gets
  rewritten on first `start_local.sh` post-cutover: if `SECRET_KEY`
  equals the dev marker, regenerate. Operator opt-out via
  `KEEP_DEV_SECRET=1` for parity-test repeatability.
- The two committed `*.env.example` files are scrubbed of any literal
  that resembles a real secret (they don't today — verified).

---

## 6 · File-upload pipeline hardening

Current pipeline (`main.py:752-809` + `media_service.py`):

1. Read first 2048 bytes, sniff MIME (`media_service.py:32-49`).
2. Pick size cap per MIME class.
3. Stream-write to `tempfile.mkstemp()`; abort on
   `bytes_written > max_size` (`main.py:781-785`).
4. Validate via Pillow / ffprobe (`media_service.py:52-83`).
5. Stream into `pg_largeobject` (`media_service.py:86-130`).
6. Return `{"asset_id": uuid, "url": "/media/{video,image}/{uuid}"}`.

v2 changes (Phase 2d):

| Change | Why | Finding |
|---|---|---|
| Reject `Content-Length > max_size` before reading body | Stop attacker pre-read cost | F-UPL-02 |
| Multi-offset MIME sniff at 0, 8, 16, 32 | Polyglot defence | F-UPL-01 |
| Explicit SVG deny + test asserting it | Future-proof | F-UPL-03 |
| Sanitise stored `filename` (strip path, ASCII-fold, 64 chars) | URL safety + log hygiene | F-UPL-04 |
| Random UUID URL (already done — keep) | Path-only obscurity | F-MED-01 |
| `Content-Disposition: inline; filename="<sanitised>"` on serve | Browser hint | F-UPL-04 |
| `X-Content-Type-Options: nosniff` (covered by §3) | MIME confusion | F-HDR-01 |
| Per-user upload rate limit (5/min) | DoS | F-UPL-02 |
| Range-cap on media serve | DoS | F-MED-01 |
| Virus-scan layer (optional, off by default) | Future-proof; spec only | parked |

The virus-scan layer (ClamAV via `clamd` socket) is **specified, not
shipped** — adds ~80MB RAM. Plumbed as a Phase-flag for v2.1:
`MEDIA_SCAN_ENABLED=true` calls `clamd.instream(tempfile)` between
steps 4 and 5; reject on hit.

---

## 7 · AuthZ enforcement boundary

Per `04 §4.4`: **the plane that receives the request enforces it.**
This doc records the authZ decision for every public route so security
review can confirm the matrix in one place.

**Vocabulary** — `04-authz-model.md` owns the canonical role-key and
permission-string vocabulary. This doc mirrors:

- Role keys (snake_case): `learner`, `feed_contributor`, `content_author`,
  `quiz_admin`, `feed_moderator`, `platform_admin`.
- Permission strings used here: `moderate.view`, `moderate.action`,
  `feed.create`, `feed.flag`, `media.upload`, `question.publish`,
  `attempt.read_any`. See `04 §3` for the full matrix.

### 7.1 Learner-plane (FastAPI) routes — authoritative list

| Route | Today | v2 target | Finding |
|---|---|---|---|
| `GET /` | session or redirect (`main.py:151-178`) | unchanged | — |
| `GET /login`, `POST /login/dev` | open (dev-only POST) | unchanged | — |
| `GET /auth/google`, `/auth/google/callback` | open (OAuth) | + PKCE | F-OAU-01 |
| `GET /logout` | session | **POST** + session | F-CSR-01 |
| `/onboarding/role`, `/profile/role` | session | session, persona only (no auth role grant) | — |
| `POST /quiz/start`, `POST /quiz/submit`, `GET /quiz/take` | session | session + `quiz_sessions` table | F-SES-02 |
| `GET /certificate/{cert_id}` | session, owner only | unchanged | — |
| `GET /history` | session | unchanged | — |
| `GET /verify`, `GET /verify/{cert_id}` | **anonymous** | anonymous + return `environment` | F-CER-02 |
| `GET /admin/attempts` | `QuizManager` | `require_permission("attempt.read_any")` | F-AUT-01 |
| `GET /auth/session-key`, `GET /auth/me` | session | unchanged | — |
| `GET /api/course/*` | anonymous | unchanged (read-only) | — |
| `GET /api/feed` | anonymous | unchanged | — |
| `POST /api/feed/flag` | `User`+ | `require_permission("feed.flag")` | F-AUT-01 |
| `POST /api/feed` | `FeedCreator` | `require_permission("feed.create")` (role: `feed_contributor`) | F-AUT-01 |
| `GET /api/moderate/queue` | `Moderator` | `require_permission("moderate.view")` | F-AUD-01 |
| `POST /api/moderate/action` | `Moderator` | `require_permission("moderate.action")` + `auth_audit` write | F-AUD-01 |
| `POST /api/admin/questions` | `QuizManager` | `require_permission("question.publish")` (role: `quiz_admin`) | F-AUT-01 |
| `POST /api/media/upload` | `FeedCreator` | `require_permission("media.upload")` (role: `feed_contributor`) + rate limit | F-AUT-01, F-UPL-02 |
| `GET /media/video/{asset_id}`, `GET /media/image/{asset_id}` | **anonymous** | anonymous (documented), Range-cap, rate limit | F-MED-01 |

### 7.2 Staff-plane (Directus) — outside this app

Directus enforces its own authZ for all CMS writes (chapters,
frameworks, question drafts, role grants). See `04 §4`.

### 7.3 Two anonymous endpoints — explicit decision

- `GET /verify*` — **must be anonymous** (the whole point is public
  cert verification). v2 keeps this and adds `environment` to the
  response.
- `GET /media/{video,image}/{asset_id}` — anonymous **by design** so
  shared feed posts work without auth. UUID-only handle (8.8×10³⁷
  guesses), rate limit, Range cap. **Gate question**: do we want this,
  or should media inherit feed visibility (which is also anonymous
  today, `/api/feed`)? Default = keep anonymous. Recorded as gate in
  §11.

### 7.4 Anonymous feed reads

`GET /api/feed` (`main.py:615-619`) is open today and per `04 §3` row 6
stays open in v2. This means the SPA can render the feed without login
— same UX as the course HTML. Security implications:

- **No user content leaks** beyond the published feed (moderation
  status filter in `storage.py:373` keeps drafts hidden — confirmed).
- **No PII** in the response (author email replaced with `userId`
  shorthand; see `main.py:535`).
- **Rate-limit** per IP at Apache to discourage scrapers (covered by
  `06`).

---

## 8 · Certificate dev-mode design (item 9, full design)

### 8.1 Problem statement

Today (`certificate.py`, `storage.py:21-46`, `main.py:378-383, 488-503`):

- DEV and PROD sign with the **same `SECRET_KEY`** if the env var is
  the same (or if both fall back to the source default).
- Cert IDs share the prefix `CCA-F-YYYYMMDD-XXXXXXXX`.
- The PDF is identical in DEV and PROD.
- The public `/verify` returns `{valid, found, attempt}` with no env
  marker. A DEV cert verifies as if it were real.

A `DEV_MODE=true` install + the in-source `SECRET_KEY` default = a
fully-functional forged-cert factory.

### 8.2 Target design (uses `03 §2.5` `signing_keys`)

| Component | DEV | STAGING | PROD |
|---|---|---|---|
| `signing_keys.key_id` | `dev-2026-01` | `staging-2026-01` | `legacy-prod` (existing rows) + `prod-2026-01` (rotation target) |
| `signing_keys.env_var_name` | `CERT_HMAC_DEV` | `CERT_HMAC_STG` | `CERT_HMAC_LEGACY` (legacy-prod row, seeded with today's `SECRET_KEY` value per C-21) / `CERT_HMAC_PROD` (rotation target) |
| `attempts.environment` | `'development'` | `'staging'` | `'production'` (default) |
| `attempts.signing_key_id` | `'dev-2026-01'` | `'staging-2026-01'` | `'legacy-prod'` (backfill) |
| Cert-ID prefix | `DEV-CCA-F-YYYYMMDD-XXXXXXXX` | `STG-CCA-F-…` | `CCA-F-YYYYMMDD-XXXXXXXX` (unchanged) |
| PDF watermark | "DEVELOPMENT — NOT VALID FOR CREDENTIALS" diagonal at 50% opacity | "STAGING — TEST CERTIFICATE" | none |
| PDF footer line | "Issued by DEPT® Academy — development environment. Not a credential." | "Issued by DEPT® Academy — staging environment." | unchanged |
| `/verify` UI badge | Red "DEVELOPMENT — not verifiable as a credential" | Yellow "Staging — test cert" | Green "Verified" |
| `/verify` response | `{valid, environment:'development', verifiable_in_production:false, …}` | …`'staging'`, `false` | …`'production'`, `true` |

**Cert-ID prefix policy — locked (gate decision Q-2):**

- **Production:** `CCA-F-YYYYMMDD-XXXXXXXX` — unchanged. Existing legacy
  certs verify byte-identical (see §8.3).
- **Non-prod:** prepend an environment tag — `DEV-CCA-F-…` for
  `development`, `STG-CCA-F-…` for `staging`. Prefix is applied at cert
  generation time per `03 §2.5` (the `signing_keys` row's environment
  drives the prefix in `main.py:378-383`).
- **Parity-regex:** `02-parity-method.md §1.5` carries the env-aware
  regex (`^(DEV-|STG-)?CCA-F-\d{8}-[A-F0-9]{8}$`) — keep 07 and 02 in
  lock-step on this.

Per `03-data-model.md §2.5` and the no-loss constraint in the shared
context: every existing `attempts` row gets
`environment='production'` + `signing_key_id='legacy-prod'`. The HMAC
input (`cert_id|email|score|submitted_at`, `storage.py:21-28`) is
unchanged, the key is unchanged, so existing PDFs verify byte-identical
on the new code.

### 8.4 Key rotation within an environment

`signing_keys.is_active` = current signer (`UNIQUE WHERE is_active`
ensures one per env). `signing_keys.can_verify` = "still accepted on
verify". `signing_keys.verify_until TIMESTAMPTZ` (column added to 03
§2.5) = the hard deadline after which `can_verify` is treated as
false regardless of its boolean state — the enforcement mechanism for
the 5-year verify window (gate decision Q-7). Rotation:

1. INSERT new row `('prod-2026-Q3', 'production', …, is_active=true,
   can_verify=true, verify_until = now() + interval '5 years')`.
2. UPDATE old row SET `is_active=false`. (Two-row atomic in a tx.) Its
   `verify_until` stays as originally set (e.g. 5 years from issuance)
   — old certs continue to verify until that wall-clock deadline.
3. New attempts get the new `signing_key_id`. Old attempts keep theirs.
4. Verifier looks up `signing_keys` by the row's `signing_key_id`,
   refuses if `can_verify=false` **or** `verify_until < now()`. Past
   `verify_until` the verifier returns `{valid:false,
   reason:"key_expired"}` and ops flips `can_verify=false` in a sweep
   job. Cross-ref `03 §2.5` for the column DDL.

### 8.5 Exact code paths to change

| File:line today | What changes |
|---|---|
| `app/storage.py:21-28` (`_sign_payload`) | Becomes `_sign_payload(cert_id, email, score, submitted_at, key_id)`. Looks up the row in `signing_keys`, reads `os.getenv(env_var_name)`, raises if missing. |
| `app/storage.py:35-46` (`verify_signature`) | Loads `signing_keys` row by `attempt.signing_key_id`; checks `can_verify`; refuses with `{valid:false, reason:"key_retired"}` if `false`. |
| `app/storage.py:118-175` (`save_attempt`) | Sets `attempt.environment` from `core/config.ENVIRONMENT` (new). Sets `attempt.signing_key_id` to the currently-active key for that environment. |
| `app/main.py:378-383` (cert-ID generation) | Prepends env prefix when env ≠ `'production'`. |
| `app/certificate.py:28-160` (PDF generation) | Reads `record["environment"]`; adds diagonal watermark text + alt footer line for non-prod. New helper `_dev_watermark(canvas, env)`. |
| `app/main.py:488-503` (`/verify` route) | Returns `environment`, `verifiable_in_production`, `signing_key_id`. Template `verify.html` renders the env badge. |
| `app/main.py:507-509` (`/verify/{cert_id}`) | Unchanged interface; same payload. |
| `core/config.py` (new) | `ENVIRONMENT = os.getenv("APP_ENV", "development" if DEV_MODE else "production")` with check enum. (Env-var name registered in `05 §1.5`.) |

The certificate code path is **the highest-risk single change** in
v2 because it touches money-equivalent artefacts. Phase 2c's first
acceptance test re-issues a known-good prod cert from a stored
attempt and binary-diffs against the original (allowing only the
`/CreationDate` field to differ).

---

## 9 · Network / process hardening

### 9.1 Firewall

Current (`deploy.sh:951-971`): ufw/firewalld opens 80 and 443 only.
**No change** for v2; verify on Phase 3c that:

- 22 (SSH) is allowed only from operator IPs (Azure NSG layer, not in
  `deploy.sh`).
- 8000 (uvicorn), 8055 (Directus, Phase 4), 5432 (Postgres) are **not**
  exposed externally.
- `ss -tlnp` audit step added to `deploy.sh` post-conditions.

### 9.2 Postgres bind

`listen_addresses='localhost'` enforced (`deploy.sh:617-635`); pg_hba
md5 host rule only for `127.0.0.1/32` (`deploy.sh:685-687`). Add a
deploy assertion (F-NET-03).

### 9.3 Directus port (Phase 4)

When Phase 4 lands Directus as a sibling Node service:

- Bind to `127.0.0.1:8055`, never 0.0.0.0.
- Reverse-proxied at `Alias /cms` from Apache.
- Same systemd hardening template as `cca-quiz`.
- Separate systemd user `directus` with its own home + nologin shell.
- Directus has its own session secret — generated like
  `deploy.sh:536-538` and stored in `/etc/directus.env`, 0600,
  `directus:directus`. Cross-ref `05-config-cms.md`.

### 9.4 systemd unit hardening (full v2 template)

```ini
[Unit]
Description=DEPT CCA Quiz (FastAPI / uvicorn)
After=network.target postgresql.service

[Service]
Type=exec
User=cca
Group=cca
WorkingDirectory=/opt/dept-anatomy/quiz-certification
EnvironmentFile=/opt/dept-anatomy/quiz-certification/.env
ExecStart=/opt/dept-anatomy/quiz-certification/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 --workers 2 \
    --proxy-headers --forwarded-allow-ips='*'
Restart=on-failure
RestartSec=5

# Existing hardening (keep)
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/opt/dept-anatomy/quiz-certification

# NEW v2 hardening (F-PRO-01, F-PRO-02)
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
# At v2 launch, ship the conservative filter only — Pillow / ffprobe
# regressions under aggressive deny-lists are well documented (C-64).
# Phase 3c runs a 24h soak with `~@resources` added; if green, the soak
# patch promotes the line below into the unit. Until then, only the
# baseline allow-list ships.
SystemCallFilter=@system-service
# SystemCallFilter=~@privileged @resources   # enable after Phase 3c 24h soak
SystemCallArchitectures=native
CapabilityBoundingSet=
AmbientCapabilities=
PrivateDevices=true
RemoveIPC=true
UMask=0027

[Install]
WantedBy=multi-user.target
```

Phase 3c writes this to `/etc/systemd/system/cca-quiz.service` via the
`deploy.sh` template.

### 9.5 TLS automation

Replace the manual `CERT_FILE`/`KEY_FILE` check (`deploy.sh:831-832,
1008-1011`) with:

```bash
if [[ ! -f "$CERT_FILE" ]] && command -v certbot &>/dev/null; then
  certbot --apache -d "$DOMAIN" --non-interactive --agree-tos \
          --email "$ADMIN_EMAIL" --redirect
fi
```

Plus `systemctl enable --now certbot.timer` for renewal. Falls back to
the existing manual flow if certbot is unavailable. Cross-ref F-NET-02.

### 9.6 Backups (F-BAK-01)

- **Nightly:** `pg_dump --format=custom --large-objects --file=/var/backups/cca-$(date +%F).dump codecoder`. 90-day retention.
- **Weekly:** offsite copy encrypted via `age -r $OPERATOR_PUBKEY` to a Backblaze B2 bucket (or Azure Blob, per VM's region). Cross-ref `05-config-cms.md` for the `BACKUP_TARGET_URL` env.
- **Restore drill:** Phase 3c runbook adds a quarterly restore test to a scratch DB on staging — green on parity harness.

---

## 10 · Phase ownership index

Each later phase's security checklist, derived from §2:

### Phase 1 (restructure + clean code, incl. FE reorg + toolchain)

- F-SEC-01, F-SEC-02 — fail-closed startup check on the `core/config.py`
  move.
- F-SEC-03 — `.env` regenerate hook in `start_local.sh`.
- F-OAU-02 — `ALLOWED_DOMAIN` startup check (paired with F-SEC).
- F-SUP-01 — pin `fastapi`/`uvicorn`; commit `requirements.lock`.
- F-SEC-03 (gitleaks) — `.pre-commit-config.yaml`.
- F-XSS-02 — remove inline `onclick` (FE reorg moves `app/js` under
  `frontend/src/` per `01-blueprint.md`).
- F-XSS-01 — renderer convention test under `tests/baseline/test_xss.py`.

### Phase 2a (DB + Alembic)

- F-SES-02 — `quiz_sessions` table (`03 §2.4`).
- F-CER-01 — `signing_keys` table (`03 §2.5`).
- F-AUD-01 — `auth_audit` table (`04 §7.4`).

### Phase 2b (authZ)

- F-AUT-01, F-AUT-02 — remove `QuizManager` bypass + dev auto-elevation.
- F-OAU-01, F-OAU-02, F-OAU-03 — PKCE + ID-token verification +
  strict domain.
- F-CSR-01 (part) — `/logout` to POST + token.

### Phase 2c (quiz + cert modules)

- F-SES-02 — quiz module reads/writes `quiz_sessions`.
- F-CER-01, F-CER-02, F-CER-03 — full cert dev-mode design (§8).

### Phase 2d (media module)

- F-UPL-01, F-UPL-02, F-UPL-03, F-UPL-04 — upload pipeline.
- F-MED-01 — anonymous serve documented + Range-cap.

### Phase 2e (security middleware seam)

- F-SES-01, F-COO-01 — `SessionMiddleware` config (§4).
- F-COR-01 — `CORSMiddleware` config.
- F-ENC-01 — startup log line stamping payload-key fingerprint.

### Phase 3a (env hardening)

- (no security findings owned here — env-mode label `APP_ENV` lands
  via `05-config-cms.md`; security defaults that *react* to it are
  covered by F-SEC-01/02 in Phase 1 and F-CER-01 in Phase 2c.)

### Phase 3b (caching / performance)

- (no security findings owned here directly; caching headers for
  `/certificate/*` and media are 06-owned but informed by §3.)

### Phase 3c (network / Apache / systemd)

- F-CSP-01, F-HDR-01 — Apache headers (§3) — handed to `06`.
- F-SUP-02 — SRI hashes on CDN scripts (paired with the CSP allow-list).
- F-NET-01, F-NET-02, F-NET-03 — TLS tightening, certbot, deploy
  assertions.
- F-PRO-01, F-PRO-02 — systemd unit (§9.4). Note: per `00 §6` C-64
  defers, `SystemCallFilter` ships as `@system-service` only at v2
  launch; aggressive filters validated by a 24h soak in this phase
  (cross-ref §9.4).
- F-UPL-02, F-MED-01 — Apache rate limit.
- F-BAK-01 — backup cron + restore drill.

### Phase 5b (final security review)

- Re-run §11 acceptance criteria. Re-run parity harness.

---

## 11 · Acceptance criteria for Phase 5b security review

A v2 release **cannot ship** to production until **all** of:

### 11.1 Hard checks (automated, in CI)

1. Startup of `cca-quiz` with `DEV_MODE=false` and unset
   `SECRET_KEY` **exits 1** within 2s. Same for unset
   `APP_PAYLOAD_SECRET`, empty `ALLOWED_DOMAIN`, missing
   `GOOGLE_CLIENT_ID/SECRET`. (F-SEC-01/02, F-OAU-02)
2. `gitleaks --no-banner` over `HEAD` returns 0 hits (or only
   baselined ones). (F-SEC-03)
3. `pip-audit` returns 0 unfixed high/critical CVEs. (F-SUP-01)
4. Response from `https://$DOMAIN/` has the seven headers from §3.1
   and a non-empty `Content-Security-Policy` matching one of the two
   profiles in §3.2. (F-CSP-01, F-HDR-01)
5. Session cookie on a logged-in browser has `HttpOnly; Secure;
   SameSite=Lax` flags and a non-default name (`cca_session`). (F-SES-01,
   F-COO-01)
6. `curl -X OPTIONS https://$DOMAIN/api/feed -H "Origin: https://evil.example"`
   returns no `Access-Control-Allow-Origin` header. (F-COR-01)
7. `/auth/google` issues a redirect with `code_challenge=` and
   `code_challenge_method=S256`. (F-OAU-01)
8. Upload of a 50MB MP4 with a JPEG-spoofed header to
   `/api/media/upload` returns 400 (not 413, not 200). (F-UPL-01)
9. `/media/image/<known-good-uuid>` from an anonymous client returns
   200. From the same client at >5 req/sec returns 429. (F-MED-01)
10. Public `/verify/DEV-CCA-F-…` returns
    `{environment: "development", verifiable_in_production: false}`.
    Public `/verify/CCA-F-…` for a real legacy cert returns
    `{valid: true, environment: "production", verifiable_in_production: true}`.
    Binary-diff a regenerated legacy PDF against the original — only
    the `/CreationDate` field differs. (F-CER-01, F-CER-02)
11. `systemctl show cca-quiz | grep -E 'NoNewPrivileges|ProtectSystem|ProtectKernel|MemoryDenyWriteExecute|SystemCallFilter'`
    shows all flags from §9.4 set. (F-PRO-01)
12. `ss -tlnp` on the VM lists only ports 22 (operator IPs), 80, 443
    publicly; 8000 (uvicorn), 8055 (Directus), 5432 (Postgres)
    bound to 127.0.0.1 only. (F-NET-03)
13. Restore drill: scratch a clean Postgres, restore from last night's
    `pg_dump`, app boots, `/verify` for a sampled cert returns
    `valid: true`. (F-BAK-01)
14. `GET /logout` returns **405 Method Not Allowed** (after F-CSR-01
    POST escalation lands). `POST /logout` without a CSRF token returns
    **403 Forbidden**. `POST /logout` with the correct CSRF token + a
    valid session clears the session and returns 302 to `/login`.
    (F-CSR-01)
15. CSP report endpoint `/csp/report` accepts a `report-to` JSON body,
    writes a structured line to journald (`SYSLOG_IDENTIFIER=cca-csp`),
    and writes **no row** to Postgres (no `security_audit` table in
    v2). (C-31, C-62)
16. Public `/verify/CCA-F-…` for a cert whose `signing_keys.verify_until
    < now()` returns `{valid: false, reason: "key_expired"}`. (C-65)
17. **COOP regression (C-33, deferred to Phase 2b):** if PKCE work in
    `04 §6.1` later switches the OAuth handshake to a popup or
    `postMessage` flow, assert `Cross-Origin-Opener-Policy` on the
    callback origin is **not** `same-origin` (must be
    `same-origin-allow-popups`). Today's top-level redirect flow keeps
    `same-origin`; no failure expected at v2 launch.

### 11.2 Manual review

18. Read every `app/js/feed/*` and `app/js/modes/feed.js` for any
    `raw()` or `innerHTML = userField`; expect zero. (F-XSS-01)
19. Read `core/security.py:install_middleware` and confirm it matches
    §4.1 and §3 verbatim.
20. Read `modules/auth/oauth.py` (new) and confirm PKCE generation,
    ID-token verification, JWKS caching, `nonce` check.
21. Read `app/storage.py` / `modules/quiz/cert.py` and confirm the
    `signing_keys` lookup is the only path to the HMAC secret.
22. Trace one moderator action end-to-end and confirm an `auth_audit`
    row is written. (F-AUD-01)

### 11.3 Pen-test scope (Phase 5b external)

- OAuth flow (state, nonce, PKCE, replay).
- Cert forgery (dev key, retired key, swapped `signing_key_id`).
- Upload polyglots + ZipSlip + decompression bombs.
- Feed XSS (try every renderer; try `&#x...`-style encodings).
- Session cookie SameSite bypass (top-level POST via form).
- Apache vhost misconfig (`Host:` header injection, path traversal
  in the two `Alias` mounts).

A clean pen-test report + 11.1–11.2 green = release gate passes.

---

## 12 · Gate questions

These are decisions this doc proposes but cannot make alone. Listed
here so Phase 0 reviewers can confirm or flip them.

1. **`/logout` GET → POST?** F-CSR-01 escalates. Cost: every "Sign
   out" link becomes a form. Benefit: closes forced-logout DoS.
   **Default: yes** (proposed). Alternative: keep GET, accept the
   minor DoS, save the UI churn.
2. **Anonymous media serve?** §7.3 keeps it open by design (so
   non-logged-in users can see shared feed content). Alternative:
   require session, drop public-feed UX. **Default: keep anonymous.**
3. **HSTS `preload`?** §3.1 includes it. Alternative: omit until
   30-day soak with non-preload. **Default: include after the 30-day
   soak; flip on at Phase 5b.**
4. **Virus-scan layer (ClamAV)?** §6 specs it but ships it off.
   Alternative: ship on, accept 80MB RAM + extra latency. **Default:
   off; revisit v2.1.**
5. **Cert-ID prefix `DEV-CCA-F-`?** §8.2. Alternative: keep the
   `CCA-F-` prefix and rely on the verifier badge alone. **Default:
   add `DEV-` prefix — the cert ID is what gets quoted on LinkedIn,
   not the verify page.**
6. **Per-session AES key only (drop static fallback)?** F-ENC-01
   parked. Alternative: ship now to make rotation zero-downtime.
   **Default: parked for v2.1.**
7. **CSP `'unsafe-inline'` for styles?** §3.2 keeps it (mermaid).
   Alternative: nonce-based + patch mermaid. **Default: keep for v2;
   nonce-based in v2.1.**
8. **`APP_PAYLOAD_SECRET` rotation drops in-flight quizzes — accept?**
   §5.2 documents the static-key derivation: rotation = restart, and
   any quiz mid-flight fails to decrypt its submit. **Default: yes —
   accept the silent drop; operators schedule rotation during a
   maintenance window.** Alternative: build a dual-decrypt seam in
   Phase 2c (tracked as F-ENC-02, currently parked). Cross-ref §11.1
   item 1.

---

**Doc version:** v2/07, draft 1 — 2026-06-05.
**Cross-doc anchors:** `04 §2.1, §3, §4.4, §6, §7.4, §8`;
`03 §2.4, §2.5, §3 step 4-5`; `01 §3, §6.4`. Phase ownership
indexed in §10. Acceptance gate in §11.
