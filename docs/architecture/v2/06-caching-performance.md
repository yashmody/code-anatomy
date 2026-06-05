# v2/06 — Caching & Performance

> Phase 0 design contract. Owner: Caching/Performance agent. Branch `v2`. **DESIGN
> ONLY — nothing here is applied yet.** Covers plan item **5 (performance / caching
> — Apache + Postgres)** and the Phase 3b checklist.
>
> Read order: `docs/architecture/v2-plan.md` → `v2/01-blueprint.md` (target tree
> for `core/cache.py`, `core/api-client.js`) → `v2/03-data-model.md` (LO lifecycle,
> pool config, `app_config`) → `v2/04-authz-model.md` (cookie / header
> intersection) → **this doc**. Coordinates with `v2/05-config-cms.md` (Directus
> webhooks fire cache invalidations) and `v2/07-security-baseline.md` (the
> always-set header set this doc must dedupe against).

All file:line citations are against branch `v2` at the time of writing.

---

## 0 · Scan box

- The current stack has **no caching at any layer**. Every API request reaches
  Postgres, every static asset is served with default Apache headers, the Apache
  vhost loads **no** `mod_cache`, `mod_deflate`, `mod_expires`, `mod_http2` or
  `mod_brotli` (`deploy.sh:822, :883-919`), and the only `Header always set` is
  HSTS (`deploy.sh:893`).
- The single largest correctness defect in this layer is **`_active_quizzes`** —
  a process-local `Dict[str, Dict]` (`quiz-certification/app/main.py:69`) that
  silently produces `404 quiz_not_found` when the submit request hits a uvicorn
  worker that didn't serve the start. `deploy.sh:42, :764` ships `--workers 2`,
  so this is broken **in production today** about half the time on `/quiz/submit`.
  03-data-model §2.3 already designs the `quiz_sessions` table that replaces it;
  this doc adopts that decision and adds the performance/operational details.
- DB schema drift hurts perf too: the four GIN/B-tree indexes that make
  `/api/feed` and quiz-pool sampling tractable
  (`idx_feed_items_ordering / topics / search`, `idx_questions_lookup`) live
  only in `deploy_schema.sql:33,54,71-73` and are **not** created by
  `Base.metadata.create_all()` — which is the actual startup path
  (`app/db.py:32`, `app/main.py:74`). A DB stood up by `init_db()` runs every
  feed listing as a sequential scan. 03 §2.8 makes them authoritative in the
  ORM; this doc audits them.
- Recommended defaults (each carries an alternative — see §10 gate decisions):
  cache backend **in-process LRU with ETag** (no Redis yet — single VM, 2
  workers); cache-bust the buildless FE via **mod_rewrite content-hash rewrites
  in Apache** (no build step, no source edits); compress with **mod_deflate
  only** (mod_brotli optional once verified available); media served with
  **`public, max-age=86400, must-revalidate`** keyed by stable `asset_id`
  (one-day browser cache, revalidates daily so moderation propagates);
  HTTP/2 enabled.

---

## 1 · Current performance posture (evidence, with file:line)

### 1.1 Apache vhost — what's there, what isn't

The vhost template lives inline in `deploy.sh`. Two relevant blocks: HTTP-only
fallback at `deploy.sh:849-876` and the TLS vhost at `deploy.sh:883-919`. The
HTTPS one is the production shape.

- **No `mod_cache`, no `mod_cache_disk`, no `mod_cache_socache`.** No caching
  proxy in front of FastAPI; every API hit traverses Apache → uvicorn → SQLAlchemy
  → Postgres.
- **No `mod_deflate`.** No gzip on JSON, HTML, CSS, JS, SVG. The 7 chapter JSON
  files alone are ~60-200KB each and compress 4-5x; the SPA ships ~15 ES modules
  uncompressed.
- **No `mod_expires`, no `mod_headers Cache-Control` per location.** Apache
  applies its defaults (no `Cache-Control` at all on static files), so browsers
  fall back to heuristic freshness — which means the SPA refetches `js/main.js`,
  `css/monolith.css` etc. on most visits.
- **No `mod_http2`.** TLS is `TLSv1.2 +TLSv1.3` (`deploy.sh:890`) but ALPN
  doesn't advertise `h2`, so every browser falls back to HTTP/1.1. Head-of-line
  blocking on the SPA bootstrap (15-20 module fetches) is non-trivial.
- **No `mod_brotli`** in the vhost; not loaded; not known to be available on the
  target VM image.
- **`a2enmod` list** at `deploy.sh:822`: `proxy proxy_http ssl rewrite headers`.
  These are the only modules deploy enables. `mod_expires`, `mod_deflate`,
  `mod_http2`, `mod_brotli` are absent.
- **Header always-set** at `deploy.sh:893`: only HSTS
  (`max-age=31536000; includeSubDomains`). 07-security-baseline will add the
  rest of the always-set headers; this doc must not duplicate them — see §2.5.
- **Aliases** at `deploy.sh:895-908`: `/anatomy → content-system/`,
  `/app → app/` (with `FallbackResource /app/index.html`). Static files served
  by Apache itself (good — no proxy hop), but with no `Cache-Control`.
- **Proxy** at `deploy.sh:910-915`: `ProxyPass / http://127.0.0.1:${QUIZ_PORT}/`
  with `ProxyPreserveHost On` and `X-Forwarded-Proto` set. No `ProxyTimeout`
  override, no connection pooling tunables.

### 1.2 App layer — every request hits Postgres

Hot endpoints (`quiz-certification/app/main.py`):

| Route | Handler | Underlying read | Frequency |
|---|---|---|---|
| `GET /api/course/framework` | `main.py:551-557` | `storage.get_framework()` → `s.get(Framework, "framework")` (`storage.py:461-464`) | **every feed render** (`app/js/feed/store.js:32`) **and** every Manual render (`util/framework.js:6`) |
| `GET /api/course/framework-explainer` | `main.py:576-606` | `storage.get_framework_explainer()` + filesystem fallback | Manual + Read on every load (`modes/scroll.js:54`, `modes/read.js:474`) |
| `GET /api/course/chapters/{filename}` | `main.py:567-573` | `s.get(CourseChapter, filename)` | 30+ section fetches in Manual mode (`main.js:18-28`) |
| `GET /api/feed` | `main.py:615-618` | `storage.get_feed_items()` — full table scan, status filter, `created_at DESC` (`storage.py:370-376`) | every Feed mount **and** `feed/store.js:112` re-reads it for `getPost(id)` |
| `POST /quiz/start` | `main.py:306-343` | `quiz_generator.generate()` — N+1 query pattern: loads all of a user's `Attempt` rows (`quiz_generator.py:59-61`) and then SELECTs questions filtered by status/difficulty/answered (`:70-78`) | once per quiz |

There is **no in-process cache, no Redis, no ETag/`If-None-Match`, no
`Last-Modified` handling.** The fetch wrapper deliberately sets `cache: 'no-cache'`
(`app/js/util/load.js:21`), so even the browser HTTP cache is bypassed for
`/api/course/*`. The framework JSON — which changes **only** when an editor
publishes from Directus (§5) — is refetched on **every** feed and manual render.

`feedStore` does keep a single module-level promise cache for categories
(`feed/store.js:26, :29-47`), which is good — but it's per-tab, and `listPosts`
itself hits `/api/feed` every call.

### 1.3 In-memory quiz session — the multi-worker bug

`main.py:69` declares `_active_quizzes: Dict[str, Dict] = {}` at module scope.
`/quiz/start` writes to it (`main.py:327-333`); `/quiz/submit` reads-and-deletes
(`main.py:367-415`).

- With `deploy.sh:42, :764` configuring `--workers 2`, the dict is **per
  uvicorn worker process**. The two workers do not share memory.
- The user's POST to `/quiz/start` lands on worker A; their later POST to
  `/quiz/submit` is load-balanced and roughly **half the time** lands on
  worker B, which has never seen `quiz_id` → `404 quiz_not_found` at
  `main.py:367-368`.
- Even on a single worker the dict is **unbounded** (no expiry sweep) and
  **lost on restart**. Every deploy abandons in-flight quizzes.

03-data-model §2.3 designs the `quiz_sessions` Postgres table. §5 of this doc
adopts that and adds the latency / cleanup details.

### 1.4 DB pool — defaults only

`app/db.py:13-19`:

```python
_engine_kwargs = {}
if config.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
engine = create_engine(config.DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

That's the *entire* engine configuration. No `pool_size`, no `max_overflow`, no
`pool_pre_ping`, no `pool_recycle`. SQLAlchemy defaults are `QueuePool`,
`pool_size=5`, `max_overflow=10` — usable at low load, but on a fresh DB
connection after a NAT/firewall idle drop or a Postgres restart, the first
request returns `OperationalError` with no automatic recovery. This is the
classic "works for 30 minutes then explodes overnight" failure.

### 1.5 Static FE — no asset hashing, no version query

`app/index.html:11-14`:

```html
<link rel="stylesheet" href="css/monolith.css">
<link rel="stylesheet" href="css/app.css">
<link rel="stylesheet" href="css/read.css">
<link rel="stylesheet" href="css/feed.css">
```

`main.js:1-6` imports 15+ ES modules by relative path. **No content hashes, no
`?v=` query strings, no `<script type="module" integrity="...">`**. The buildless
design (a locked decision) means we cannot add a bundler; cache-busting must be
solved without source edits — §3.

### 1.6 Media — large objects, no app cache, no CDN

`app/media_service.py:133-153` streams `pg_largeobject` chunks at 256KB; the
endpoint handles `Range` (`main.py:822-847`). There is no in-process media
cache, no `Cache-Control` on the response, no `ETag`, no `Vary` — and (since
06's Apache config doesn't proxy-cache) every byte traverses Postgres on every
request. `asset_id` is a stable UUID per upload (`media_service.py:110`), so the
URL is byte-stable for a given id — making it a strong candidate for a long
browser TTL. We deliberately stop short of `immutable` because moderated or
deleted media must drop out of intermediate caches within a day, not a year
(§2.4 settles on `public, max-age=86400, must-revalidate`).

### 1.7 Schema indexes — present in DDL, absent in `create_all`

03-data-model §1.9.2 documents this in detail. In short, the live system today
depends on which path stood up the DB:

- DB created by `deploy_schema.sql` (run by `deploy.sh:706`): has
  `idx_questions_lookup (status, difficulty, topic)` (`deploy_schema.sql:33`),
  `idx_attempts_user (user_email, submitted_at DESC)` (`:54`),
  `idx_feed_items_ordering (status, created_at DESC)` (`:71`),
  `idx_feed_items_topics USING gin (topics)` (`:72`),
  `idx_feed_items_search USING gin (search)` (`:73`).
- DB created by `init_db()` → `Base.metadata.create_all()` (`db.py:32`, the
  startup path at `main.py:74`): has **none** of those four, and **no**
  generated `search` tsvector column. Feed listing falls back to a seq scan
  over `feed_items` + sort.

03 §2.8 and §3 step 2 fix this — the ORM gets the indexes, Alembic carries the
`CREATE INDEX IF NOT EXISTS` for already-migrated DBs.

---

## 2 · Apache hardening — concrete vhost additions for v2

The vhost template stays inline in `deploy.sh` (per 01 §3 — Phase 1 may extract
to `infra/apache/vhost.conf.template` but does not have to). What follows is a
**drop-in addition** that Phase 3b applies to the HTTPS vhost block
(`deploy.sh:883-919`). The HTTP vhost only redirects, so it gets HSTS + nothing
else.

### 2.1 New modules to enable

Append to the `a2enmod` loop at `deploy.sh:822`:

```bash
for mod in proxy proxy_http ssl rewrite headers \
           deflate expires http2 cache_socache socache_shmcb ratelimit; do
  a2enmod "$mod" >/dev/null 2>&1 || true
done
```

- `deflate` — compression (required).
- `expires` + `headers` (already on) — `Cache-Control` / `Expires`.
- `http2` — HTTP/2 over TLS.
- `cache_socache` + `socache_shmcb` — small shared in-memory cache, only used
  if §10 decision flips Redis → "no" and we want a tiny edge cache for
  framework-explainer (deferred; not on by default).
- `ratelimit` — `mod_ratelimit` for outbound-bandwidth throttling on the
  one route that needs it (media upload). 07-security-baseline delegates
  bandwidth-rate-limiting to this doc; the abuse-rate-limiting (per-IP
  request count for `/auth/*`) remains owned by 07 via its own seam.

For RHEL: `mod_http2`, `mod_deflate`, `mod_expires`, `mod_ratelimit` ship
with the `httpd` package on RHEL 8+ (no extra install).

The `/api/media/upload` route is the only endpoint where a misbehaving
client can saturate the uplink (large multipart bodies, video). Cap
outbound bandwidth per response:

```apache
<Location "/api/media/upload">
    SetOutputFilter RATE_LIMIT
    SetEnv rate-limit 4096
</Location>
```

`rate-limit 4096` is KB/s per response (so ~4 MB/s per active upload — well
within a single VM's uplink but bounded enough to stop a runaway client
from monopolising the link). Tighten in Phase 3c if real traffic warrants;
07-security-baseline §11.1 owns the regression assertion.

### 2.2 HTTP/2 — enable ALPN inside the `*:443` block

Insert into the TLS vhost at `deploy.sh:883-919`, **before** `SSLEngine on`:

```apache
Protocols h2 http/1.1
```

Apache 2.4.17+ honours this when `mod_http2` is loaded; `h2c` (cleartext HTTP/2)
is deliberately omitted — port 80 only redirects. Combined with the existing
`SSLProtocol -all +TLSv1.2 +TLSv1.3` (`deploy.sh:890`) this is the entire
HTTP/2 enablement.

> Caveat: `mpm_prefork` + `mod_http2` warns but works; production should use
> `mpm_event` (Ubuntu's `apache2-mpm-event` package, default on 20.04+; on
> RHEL switch with `a2dismod mpm_prefork && a2enmod mpm_event` analogue —
> `httpd.conf` LoadModule on RHEL). Phase 3b verifies the MPM at deploy time.

### 2.3 Compression — mod_deflate

Add inside the `*:443` vhost (anywhere before the `</VirtualHost>`):

```apache
<IfModule mod_deflate.c>
    # Compress text-ish content. Don't compress already-compressed binaries.
    AddOutputFilterByType DEFLATE \
        text/html \
        text/plain \
        text/css \
        text/xml \
        text/javascript \
        application/javascript \
        application/json \
        application/xml \
        application/xhtml+xml \
        application/rss+xml \
        image/svg+xml \
        font/ttf \
        font/otf
    # Don't deflate ranges (media endpoint serves Range requests).
    SetEnvIfNoCase Request_URI "^/media/" no-gzip dont-vary
    # Some old proxies break on gzipped responses; mark as varying.
    Header append Vary Accept-Encoding env=!dont-vary
</IfModule>
```

Verified-uncompressed types: video (`video/mp4`, `video/webm`), images (`jpeg`,
`png`, `webp`), woff/woff2 fonts — all already compressed at the format level.

### 2.4 Cache-Control per location — `mod_expires` + `mod_headers`

The matrix:

| URL pattern | Cache-Control | Why |
|---|---|---|
| `/app/index.html` | `no-cache, must-revalidate` | The SPA entrypoint — must be fresh so new hashed asset URLs in it are picked up. Re-validation is cheap (ETag). |
| `/app/js/**/*.js`, `/app/css/**/*.css` (unhashed source) | `no-cache, must-revalidate` (fallback) | The buildless source files. Default rule — overridden by §3 hashed-URL rewrites. |
| `/app/css/v=HASH/*.css`, `/app/js/v=HASH/*.js` (rewritten — §3) | `public, max-age=31536000, immutable` | Hashed-URL form. Content-addressed, safe to cache forever. |
| `/anatomy/anatomy-of-code-course.html` (frozen monolith) | `public, max-age=3600, must-revalidate` | Changes rarely; 1h survives navigation patterns, ETag handles the rare update. |
| `/anatomy/**` (other static, runbooks, FAQs) | `public, max-age=3600, must-revalidate` | Same logic. Long-tail static content. |
| `/api/course/framework` | `private, max-age=300, must-revalidate` | Editor-controlled; 5-minute browser window is acceptable. Invalidated server-side via §4 when Directus publishes. |
| `/api/course/framework-explainer` | `private, max-age=300, must-revalidate` | Same. |
| `/api/course/chapters/*` | `private, max-age=300, must-revalidate` | Per-chapter, same logic. |
| `/api/feed` | `private, no-cache` (revalidate every time) | UGC stream; readers expect to see new posts. ETag/304 carries the savings (§4). |
| `/api/feed/flag`, `/api/feed` (POST), `/api/moderate/*`, `/api/admin/*`, `/api/media/upload`, `/quiz/*` | `no-store` | Authenticated writes / private quiz state. Never cache. |
| `/media/image/{id}`, `/media/video/{id}` | `public, max-age=86400, must-revalidate` | `asset_id` is a stable UUID, but assets can be moderated or deleted; one-day window with revalidation lets a takedown propagate without keeping bytes alive at intermediate caches for a year. |
| `/auth/*` (`/auth/me`, `/auth/google`, `/auth/google/callback`, `/auth/session-key`) | `no-store, private` | Identity / token flows. Never cache. |
| `/login*`, `/logout`, `/onboarding/*`, `/profile/*` | `no-store, private` | Auth + session state. |
| `/certificate/{cert_id}` | `private, max-age=86400, must-revalidate` + `Vary: Cookie` | The PDF is byte-stable once issued; **user-private** — `private` forbids shared-cache storage, `Vary: Cookie` defends in depth against a misconfigured proxy serving one user's PDF to another. |
| `/verify*` | `no-cache` | Public verification — always check the DB. |

The vhost block:

```apache
<IfModule mod_expires.c>
    ExpiresActive On
</IfModule>

<Location "/app/">
    <Files "index.html">
        Header always set Cache-Control "no-cache, must-revalidate"
    </Files>
</Location>

# Default rule for /app/ static — overridden per-path-pattern below.
<Directory "${APP_HOME}/app">
    Header always set Cache-Control "no-cache, must-revalidate"
</Directory>

# Hashed-URL static (§3) — long immutable cache.
<LocationMatch "^/app/(js|css)/v=[a-f0-9]{8,}/">
    Header always set Cache-Control "public, max-age=31536000, immutable"
</LocationMatch>

# Renamed/missing hashed JS or CSS must 404 cleanly — never serve the SPA
# index.html as fallback for these subpaths (see §2.8 FallbackResource scope).
<LocationMatch "^/app/(js|css)/">
    FallbackResource disabled
</LocationMatch>

# Course content (Directus-edited; short browser TTL + ETag).
<LocationMatch "^/api/course/">
    Header always set Cache-Control "private, max-age=300, must-revalidate"
</LocationMatch>

# Feed: revalidate always, but allow conditional-GET savings via ETag.
# Single source of truth — the rule is parameterised at the app layer
# (§4.4 `cached_response(..., cache_control=...)`); Apache sets the same
# value here for cases where the response originates from Apache (304/error).
<Location "/api/feed">
    Header always set Cache-Control "private, no-cache"
</Location>

# Media: stable id ⇒ public, must-revalidate. **Not** `immutable` — a
# moderated/deleted asset must not survive in intermediate caches for the
# full TTL window. Browsers revalidate via ETag on the next visit.
<LocationMatch "^/media/(image|video)/">
    Header always set Cache-Control "public, max-age=86400, must-revalidate"
</LocationMatch>

# Certificate PDFs — user-private, byte-stable once issued. `Vary: Cookie`
# prevents a shared cache from cross-serving between users; `private`
# forbids intermediary storage entirely; `must-revalidate` means stale
# responses are never used without revalidation.
<LocationMatch "^/certificate/">
    Header always set Cache-Control "private, max-age=86400, must-revalidate"
    Header always set Vary "Cookie"
</LocationMatch>

# Anatomy static.
<Directory "${APP_HOME}/content-system">
    Header always set Cache-Control "public, max-age=3600, must-revalidate"
</Directory>

# Always-uncacheable surfaces.
<LocationMatch "^/(login|logout|onboarding|profile|auth|quiz|verify)">
    Header always set Cache-Control "no-store, private"
</LocationMatch>
<LocationMatch "^/api/(moderate|admin|media/upload|feed/flag)">
    Header always set Cache-Control "no-store, private"
</LocationMatch>
```

> **Why `Header always set` (not `Header set`):** plain `Header set` only
> applies to 2xx/3xx final responses. Conditional-GET round trips return
> `304 Not Modified` and error pages return 4xx/5xx; both must still carry
> the `Cache-Control` directive (otherwise a `304` becomes a heuristically
> cached response with no freshness rule, and a 5xx can be served from a
> stale cache indefinitely). `Header always set` covers every response
> table including 304 and 5xx.

> **Phase-3b note:** these `Header always set Cache-Control` directives sit
> alongside 07-security-baseline's `Header always set` block
> (`X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, CSP)
> — both use `always set` because both must apply to error responses (a
> 5xx without `Cache-Control` is a stale-cache hazard; a 304 without
> `Cache-Control` is a heuristic-freshness hazard). Phase 3b owns the merge;
> 07 owns the authoritative security header list.

### 2.5 ETag & Last-Modified strategy

- **Static (Apache-served):** `mod_core` already emits weak `ETag` + `Last-Modified`
  from inode/mtime/size. Behind a single VM this is fine. On RHEL these get an
  inode component which differs across machines; not relevant for the single-VM
  topology, but Phase 3b notes it for future HA.
- **API (FastAPI-served):** FastAPI does not emit `ETag` by default. The
  app-cache layer (§4) computes a SHA-256 of the serialised JSON body and emits
  `ETag: "<8-hex-of-sha256>"`. `If-None-Match` short-circuits to `304 Not
  Modified` before any DB read. This is the single biggest win for
  `/api/course/*` — payloads of 200KB+ collapse to a 304.
- **Apache must not strip ETags on proxy responses.** No special config needed
  — `ProxyPassReverse` keeps response headers intact; verify in §8 smoke.

### 2.6 Brotli — defer

`mod_brotli` ships with Apache 2.4.26+ but is **not** in the default Ubuntu
20.04 / RHEL 8 `apache2`/`httpd` packages without extra install
(`libapache2-mod-brotli` on Debian; EPEL on RHEL). Tradeoffs:

- Better compression than gzip on text (typical 15-25% improvement for JSON
  and HTML).
- Server-side CPU cost is higher than gzip at default quality; mitigated by
  caching gzip/br output via `mod_cache` + `mod_cache_disk` — but that adds
  another moving part.
- Pre-compressed `.br` files alongside `.js`/`.css` would work with the
  buildless decision (no rebuild step needed if §3 hashed-URL rewrites are
  used), but require us to pre-generate them in `deploy.sh`.

**Recommendation:** ship v2 with `mod_deflate` only. Re-evaluate Brotli after
the first month of real traffic data. Gate decision §10 #2.

### 2.7 Proxy & connection tunables (small additions)

Inside the `*:443` vhost, after `ProxyPreserveHost On`:

```apache
ProxyTimeout 60
ProxyBadHeader Ignore

# Add Server-Timing and X-Cache headers to API responses for diagnostics.
<LocationMatch "^/api/">
    Header set X-Cache "%{X-Cache-Backend}e" env=X-Cache-Backend
</LocationMatch>
```

`ProxyTimeout 60` matches uvicorn's keep-alive ceiling (default 5s, but the
slowest hot endpoint — `/quiz/start` — has at most 5 DB queries; 60s leaves
margin for a momentary stall). 03 sets a 45-minute quiz duration but that's a
client-side timer; no proxy timeout depends on it.

### 2.8 `FallbackResource` scope — protect hashed JS/CSS from HTML fallback

The current vhost (`deploy.sh:895-908`) sets `FallbackResource /app/index.html`
on the `/app` alias so SPA deep links resolve to the bootstrap HTML. That's
correct for `/app/feed`, `/app/manual/...` etc. — but **wrong** for
`/app/js/*` and `/app/css/*`: if a deploy renames `main.js` to a new hashed
URL and an old tab still references the previous path, the browser asks for
`main.js`, Apache 404s on disk, then `FallbackResource` rewrites the
response to `index.html` — and the browser tries to *execute HTML as
JavaScript*. Result: silent failure (no console error from the network
layer; only a parse error after the body arrives).

The fix is one extra `<LocationMatch>` that disables `FallbackResource` for
the JS/CSS subpaths, embedded in the §2.4 block above:

```apache
<LocationMatch "^/app/(js|css)/">
    FallbackResource disabled
</LocationMatch>
```

With this in place, a stale URL returns a clean `404` and the SPA can
recover (or the user gets an honest error). The HTML fallback continues to
work for every other `/app/*` path.

> This guard is essential once §3 cache-busting ships — without it, the
> safety of "rollback is just an old `index.html`" doesn't actually hold.

---

## 3 · Cache-busting for the buildless FE (§1.5 → fix)

The buildless promise (v2-plan.md:27) says no bundler. Options considered:

| Option | Effort | Editor cost | Robustness | Verdict |
|---|---|---|---|---|
| **Query-string version (`main.js?v=hash`)** | low | medium — every `<link>` and `<script>` must be edited, plus relative imports inside JS modules cannot have query strings stripped by browsers — works in HTML, **breaks** ES-module import URLs because the browser dedupes by full URL but cache-keys by full URL | partial | ✗ — `main.js?v=abc` and `main.js?v=def` are *different* module instances in the import graph; can break the singleton pattern in `auth-ui.js` etc. |
| **File rename (`main.abc123.js`)** | medium | high — every import path inside source files would change on every deploy | strong | ✗ — violates "no source edits", requires regeneration of every cross-import |
| **mod_rewrite content-hash URLs** | low | **none** — Apache rewrites `/app/js/v=abc/main.js` → `/app/js/main.js` server-side; HTML just gets the hashed URL inserted at deploy time | strong | ✓ **recommended** |
| **Tiny build step** (Python script in `deploy.sh` that rewrites href/src) | low | none in source; one new step in deploy | strong | ✓ acceptable alternative |
| **Service Worker** | high | high — code, debugging, mental model | strong | ✗ overkill |

### 3.1 Recommended: mod_rewrite hashed-prefix pattern

The URL the browser sees is `/app/js/v=ab12cd34/main.js`. Apache rewrites the
`v=…/` segment away before disk lookup, so the file is still `/app/js/main.js`
— no rename, no edit. Long-lived immutable cache because the hash is part of
the URL.

```apache
# Strip a content-hash version segment so /app/js/v=<hash>/foo.js
# serves /app/js/foo.js. The Cache-Control rule (§2.4) matches the same
# prefix and applies "immutable, 1 year".
RewriteEngine On
RewriteRule ^/app/(js|css)/v=[a-f0-9]{8,}/(.+)$ /app/$1/$2 [L]
```

A small Python helper run at the end of `deploy.sh` (after the rsync) rewrites
**only** `/app/index.html`:

```python
# infra/cachebust.py — runs once per deploy.
import hashlib, re, pathlib
APP = pathlib.Path("/opt/dept-anatomy/app")  # APP_HOME/app
index = APP / "index.html"
def h(rel):
    p = APP / rel
    return hashlib.sha256(p.read_bytes()).hexdigest()[:10]
text = index.read_text()
text = re.sub(
    r'(href|src)="(js|css)/([^"?#]+)"',
    lambda m: f'{m[1]}="{m[2]}/v={h(m[2] + "/" + m[3])}/{m[3]}"',
    text,
)
index.write_text(text)
```

Properties:

- **Source files untouched** — only the deployed copy of `index.html` is
  modified.
- **ES-module imports inside the JS** are still relative (`from './foo.js'`),
  resolving against the *rewritten* URL of the importing module — but Apache
  rewrites both ends back to the same physical files. The browser caches each
  hashed URL independently, but the network only requests them once each.
- **Atomic deploys:** because `deploy.sh` rsyncs new bytes *then* runs the
  cachebust helper, an inflight request hitting a half-written tree can't get
  a stale-hashed URL pointed at fresh content — the HTML is rewritten last.
- **Rollback:** Apache's `RewriteRule` ignores the version segment, so an old
  `index.html` referencing `/app/js/v=oldhash/main.js` still serves the
  current `main.js` — no breakage on rollback, just suboptimal caching for
  one window.

### 3.2 Alternative — small in-deploy build step (no Apache rewrite)

Same Python script, but it **renames** the deployed files (`main.js` →
`main.ab12cd34.js`) and rewrites references. Avoids the Apache rewrite rule;
costs a small amount of complexity in deploy. Either approach is acceptable;
recommended is mod_rewrite because it's stateless (re-running deploy is
idempotent without filename collisions).

Gate decision §10 #3.

---

## 4 · Application-layer cache — where it lives, what it does

### 4.1 Where: `backend/app/core/cache.py` (01-blueprint §1)

01-blueprint.md introduces `app/core/cache.py` as a seam for Phase 3b
(01-blueprint.md:44). This doc fills the seam.

```python
# backend/app/core/cache.py — Phase 3b implements.
from typing import Any, Awaitable, Callable, Optional
import hashlib, json, time, asyncio

class CacheEntry:
    __slots__ = ("value", "etag", "expires_at")
    def __init__(self, value, etag, expires_at): ...

class AppCache:
    """In-process TTL+LRU cache with stable ETags.

    Backend chosen at startup from APP_CACHE_BACKEND env (see §10):
      - 'memory'  → per-process dict + asyncio.Lock (default)
      - 'redis'   → aioredis (only if 4+ workers, Phase 3b stretch)
    """
    async def get_or_set(
        self, key: str, ttl_seconds: int,
        producer: Callable[[], Awaitable[Any]],
    ) -> tuple[Any, str]: ...
    async def invalidate(self, key_prefix: str) -> int: ...
    def etag_for(self, value: Any) -> str: ...
```

The producer is the existing DB read (e.g. `storage.get_framework()`); the
cache wraps it with TTL + stable ETag computed as
`sha256(canonical_json(value))[:16]`. `invalidate(prefix)` is called by the
Directus webhook receiver in `modules/cms/routes.py` (01-blueprint.md:77).

### 4.2 Backend choice — in-process LRU, not Redis (default)

Tradeoffs at the 2-worker uvicorn topology (`deploy.sh:42, :764`):

| Property | In-process LRU | Redis |
|---|---|---|
| Inter-worker coherency | none — each worker has its own copy | strong |
| Add new infra | none | one more service to install, monitor, secure |
| Memory budget | small (a few MB per worker) | ~64MB instance minimum |
| Invalidation latency | per-process; webhook fan-out via FastAPI's BroadcastChannel or just "next request" miss | atomic |
| Bound on number of workers | scales linearly: more workers = more wasted dupes; reasonable up to ~4 | unbounded |

At **2 workers serving framework/explainer/feed content** the wasted dupe is
two copies of ~250KB of JSON — trivial. The harder question is **how a
write becomes visible across both workers**.

**Recommendation: TTL-only invalidation.** Short TTLs make staleness
self-healing — a worker that missed a webhook recovers on the next TTL
expiry. Concretely:

- Framework / framework-explainer / chapters: **15-minute TTL.** A
  publishing event is worst-case 15 minutes late on one worker. Acceptable
  for an editor-driven content site at this audience size.
- Feed: **30-second TTL.** UGC stream; a freshly-posted item appears within
  half a minute even if every webhook is dropped.
- `app_config`: **60-second TTL** (already short enough that no LISTEN
  channel is worth the complexity).

The webhook receiver in `modules/cms/routes.py` (§9 Block B step 7) still
calls `cache.invalidate(prefix)` on the **local** worker — so the worker
that received the webhook is instant; the other worker(s) catch up at the
next TTL boundary. That is the entire invalidation story at 2 workers.

Cross-worker invalidation broadcast (LISTEN/NOTIFY, Redis pub/sub, sidecar
channels) is deliberately **not** in the default design — it adds real
operational complexity (sync `psycopg2` driver alongside async SQLAlchemy,
async reconnect on Postgres restart, 8000-byte `NOTIFY` payload cap,
listener-thread lifecycle) for a problem that affects two workers for
worst-case 15 minutes. Documented as gate decision §10 #1 alternative.

If we ever scale to 4+ workers or add a second VM, swap the backend to
Redis behind the same `AppCache` interface; the seam in `core/cache.py` is
designed exactly for this swap. Gate decision §10 #1.

### 4.3 What gets cached, with TTL and invalidation triggers

| Cache key | Source | TTL | Invalidated by (local worker only — other workers wait for TTL) |
|---|---|---|---|
| `course:framework` | `storage.get_framework()` | **900s (15 min)** | Directus webhook on `frameworks` collection write |
| `course:framework-explainer` | `storage.get_framework_explainer()` | **900s** | Directus webhook on `frameworks` collection write (same row family) |
| `course:chapters:list` | `storage.get_all_chapters()` (just `{filename, ring, title}`) | **900s** | Directus webhook on `course_chapters` |
| `course:chapter:{filename}` | `storage.get_chapter(filename)` | **900s** | Directus webhook on `course_chapters` row (key prefix invalidate by filename) |
| `feed:list:published` | `storage.get_feed_items()` | **30s** | `POST /api/feed`, `POST /api/feed/flag`, `POST /api/moderate/action` |
| `feed:list:moderation_queue` | `storage.get_moderation_queue()` | 30s | Same write paths |
| `quiz:topic_summary` | `quiz_generator.topic_summary()` (`main.py:162`, expensive — loads every published Question) | 600s | Directus webhook on `questions`, `POST /api/admin/questions` |
| `app_config:{key}` | row from `app_config` table (03 §2.4) | 60s | Directus webhook on `app_config` |

Hot endpoints **not** cached:

- `/api/feed` itself is wrapped, but the *user-specific* dimension (auth
  cookie) means we cache the **published list** body but emit
  `Cache-Control: private` to keep proxies out.
- `/quiz/start`, `/quiz/submit`, `/auth/me`, `/auth/session-key` — user-bound,
  side-effecting. Never cached.
- `/certificate/{cert_id}` — generated PDF; the HTTP cache layer
  (`private, max-age=86400, must-revalidate` + `Vary: Cookie`; §2.4) carries
  the savings; user-private so we never cache server-side.
- `/media/video|image/{asset_id}` — streamed; the **HTTP cache** layer
  (`public, max-age=86400, must-revalidate`; §2.4) plus ETag on the
  range-stream handler carries the savings. App-side caching of LO bytes
  would blow the memory budget.

### 4.4 Conditional GET — ETag + `If-None-Match`

The cache layer is the natural home for ETag generation. A FastAPI dependency
wraps the relevant GET routes. The `cache_control` directive is parameterised
per route — there must be **one** rule per URL pattern, declared at the call
site, never duplicated across Apache + the app.

```python
# backend/app/core/cache.py (sketch)
async def cached_response(
    request,
    key: str,
    ttl: int,
    producer,
    cache_control: str,
):
    value, etag = await app_cache.get_or_set(key, ttl, producer)
    if request.headers.get("if-none-match") == etag:
        # 304 MUST carry Cache-Control too — otherwise the browser falls
        # back to heuristic freshness on the cached body. Pairs with the
        # `Header always set Cache-Control` directive in §2.4 (which
        # covers responses that originate from Apache, e.g. when the
        # upstream times out).
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": cache_control},
        )
    return JSONResponse(
        value,
        headers={"ETag": etag, "Cache-Control": cache_control},
    )
```

Call sites (one rule per route — no duplication across Apache and app):

```python
# backend/modules/course/routes.py
@router.get("/api/course/framework")
async def get_framework(request: Request):
    return await cached_response(
        request,
        key="course:framework",
        # Server-side TTL (in-process cache): 15 min — matches §4.3.
        ttl=900,
        producer=storage.get_framework,
        # Browser-side: 5 min + must-revalidate. ETag covers the round-trip
        # after that. The two TTLs are independent on purpose — the
        # server-side one bounds DB reads, the browser-side one bounds
        # repeat fetches.
        cache_control="private, max-age=300, must-revalidate",
    )

# backend/modules/feed/routes.py
@router.get("/api/feed")
async def list_feed(request: Request, user=Depends(current_user)):
    return await cached_response(
        request,
        key="feed:list:published",
        ttl=30,
        producer=storage.get_feed_items,
        # Single source of truth: Apache (§2.4) emits the same string;
        # client-controllable revalidation via ETag on every request.
        cache_control="private, no-cache",
    )
```

The FE `api-client` (01-blueprint.md:103, `core/api-client.js`) tracks the
last seen `ETag` per URL in a `Map` and sends `If-None-Match` on the next
request. On `304`, the client returns the cached body (kept in a per-tab
`Map`). This buys repeat-load performance without a service worker.

**Important:** this means `loadJSON` must **stop** sending `cache: 'no-cache'`
(`app/js/util/load.js:21`). That flag forces a full revalidation that bypasses
the ETag savings on the framework JSON. Phase 1 swap when moving to the new
`api-client`.

---

## 5 · Quiz session persistence (§1.3 → fix, coordinates with 03 §2.3)

03-data-model §2.3 designs the `quiz_sessions` table. Adopt verbatim. The
performance picture this doc adds:

- **Latency:** `/quiz/start` adds 1 INSERT (the row). `/quiz/submit` becomes
  1 `SELECT ... FOR UPDATE` + 1 `UPDATE submitted_at`. With the index
  `idx_quiz_sessions_user (user_email)` and PK on `quiz_id`, both are
  sub-millisecond on warm Postgres. Compared to the in-memory dict's ~5μs,
  this is ~1-2ms additional latency — acceptable for a 30-question quiz.
- **Volume:** at the practice scale (architects across DEPT®, ~hundreds of
  active learners), peak in-flight is at most a few hundred rows. The table
  fits in shared_buffers entirely.
- **DB vs Redis (re-affirms 03 §2.3):** Postgres wins because:
  1. `/quiz/submit` writes a `quiz_sessions.submitted_at` and inserts an
     `attempts` row in **the same transaction** — atomicity matters here
     (replay protection).
  2. No new infrastructure.
  3. The volume is trivial.
  Redis would only win if quiz submission was a hot path with thousands per
  second. We are nowhere near that.
- **Cleanup job:** `DELETE FROM quiz_sessions WHERE expires_at < now() -
  interval '1 day'` runs from a small `backend/scripts/sweep.py`. Wire into
  systemd as a daily timer (Phase 3b). Pairs with the `vacuumlo` job (§6.4).
- **Expiry semantics:** `/quiz/submit` rejects with 410 Gone if `now() >
  expires_at`. Today the dict has no expiry — the frontend's
  `duration_minutes` timer is the only check. The DB enforces it server-side
  too.

---

## 6 · Postgres tuning — single-VM topology

### 6.1 `postgresql.conf` starting values

The current deploy doesn't touch `postgresql.conf` beyond `listen_addresses`
(`deploy.sh:613-636`). Phase 3b adds a managed config file (or appends a
`Include 'dept-anatomy.conf'` line). Starting values for a small VM
(4 vCPU / 8GB RAM is the assumed Azure baseline per `deploy.sh:43`):

```ini
# /etc/postgresql/conf.d/dept-anatomy.conf  (Phase 3b creates this)

# Memory
shared_buffers              = 1GB         # 25% of RAM is the rule of thumb
effective_cache_size        = 4GB         # OS+PG combined, ~50% of RAM
work_mem                    = 16MB        # per sort/hash; we have JSONB + GIN
maintenance_work_mem        = 256MB       # VACUUM/CREATE INDEX

# Connections — pool calc in §6.2
max_connections             = 100         # generous; pool stays under

# WAL / checkpoints
wal_compression             = on
checkpoint_timeout          = 15min
max_wal_size                = 2GB
checkpoint_completion_target = 0.9

# Planner
random_page_cost            = 1.1         # SSD; default 4.0 is HDD-era
effective_io_concurrency    = 200         # SSD

# Logging — minimal but useful for §8 baselines
log_min_duration_statement  = 500ms       # only slow queries
log_checkpoints             = on
log_lock_waits              = on
log_temp_files              = 10MB
```

These are starting points. Phase 3b runs `pgbench` + the §8 smoke and
re-tunes. On RHEL the config lives at `/var/lib/pgsql/<ver>/data/postgresql.conf`;
on Debian `/etc/postgresql/<ver>/main/postgresql.conf` — the deploy
`pg_hba_path()` helper at `deploy.sh:239-255` already knows both layouts and is
the right place to extend.

### 6.2 Connection pool — `pool_size`, `max_overflow`, `pool_pre_ping`, `pool_recycle`

Fix `db.py:13-19`. Pool sizing is tuneable via two env vars — `DB_POOL_SIZE`
and `DB_MAX_OVERFLOW` — **registered in 05-config-cms.md §1.5** as Tier 2
env config (no secret material; safe to set in `.env.production.example`).

```python
# backend/app/core/db.py
import os
from sqlalchemy import create_engine

# Defaults match the 2-worker sizing math below; override per environment
# via DB_POOL_SIZE / DB_MAX_OVERFLOW (registered in 05 §1.5).
_pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))

engine = create_engine(
    config.DATABASE_URL,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_pre_ping=True,    # eliminates "OperationalError after idle" failures
    pool_recycle=1800,     # recycle every 30 min (under Postgres idle_in_transaction)
    future=True,
)
```

Pool sizing at 2 workers (default `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=10`):

- Each uvicorn worker has its **own** SQLAlchemy `engine` (it's
  module-imported, no fork-share). With `pool_size=5, max_overflow=10`, each
  worker can use up to 15 DB connections — **30 total at 2 workers**.
- `max_connections=100` in Postgres leaves headroom for psql sessions, the
  ETL script, and a future Directus connection (Directus pool is configured
  in its own service config — Phase 4 sets it to 10).
- If we move to 4 workers: keep `DB_POOL_SIZE=5` / `DB_MAX_OVERFLOW=10`,
  total 60, still well under 100. Tune via env, no code change.

At 8+ workers we'd switch to PgBouncer in front of Postgres and shrink each
SQLAlchemy pool to 2-3. Not needed at v2 launch; mentioned for future scale.

### 6.3 Index audit — confirm Alembic carries everything

Per 03 §2.8, all of these become ORM-defined and migration-carried in Phase 2a.
This doc checks them off and adds the new tables' indexes:

| Table | Index | Source today | Lands in (03 §2.8 / new) |
|---|---|---|---|
| `questions` | `(status, difficulty, topic)` | DDL only (`deploy_schema.sql:33`) | ORM (03 §2.8) |
| `attempts` | `(user_email, submitted_at DESC)` | DDL only (`:54`) | ORM (03 §2.8) |
| `attempts` | `(cert_id)`, `(passed)` | ORM (`models.py:76, :86`) | already authoritative |
| `attempts` | `(environment)` | **new** | 03 §2.1, this doc confirms |
| `feed_items` | `(status, created_at DESC)` | DDL only (`:71`) | ORM (03 §2.8) |
| `feed_items` | `gin (topics)` | DDL only (`:72`) | ORM (03 §2.8) |
| `feed_items` | `gin (search)` | DDL only (`:73`) | ORM (03 §2.8) |
| `quiz_sessions` | `(user_email)`, `(expires_at)` | **new** | 03 §2.3 |
| `user_roles` | `(role_key)` | **new** | 03 §2.2 |
| `app_config` | PK on `key` | **new** | 03 §2.4 |
| `signing_keys` | unique partial `(environment) WHERE is_active` | **new** | 03 §2.5 |
| `media_assets` | `(large_object_oid)` | **new** | 03 §2.7 — needed for the cleanup job (§6.4) |

One additional index this doc recommends:

- `CREATE INDEX idx_app_config_keys_prefix ON app_config (key text_pattern_ops)` —
  if 05-config-cms.md ends up using `LIKE 'quiz.%'` prefix queries from the
  admin UI. Optional; only if 05 needs it.

> **Not recommended** (deliberately struck): an explicit
> `idx_attempts_test_code (test_code)` B-tree. 03 §2.1 declares
> `attempts.test_code` `UNIQUE`, which in Postgres already creates a usable
> btree-backed unique index — adding a second non-unique B-tree on the same
> column is pure duplication. The verify-by-code flow and the
> `_generate_unique_code` collision check (`storage.py:184`) both use the
> unique index directly.

### 6.4 `vacuumlo` schedule — cross-ref 03 §7

Postgres ships `vacuumlo` (in `postgresql-contrib` on Debian, `postgresql-contrib`
on RHEL). It walks every table looking for `oid` columns referencing
`pg_largeobject` and unlinks orphans. 03 §7 designs the cleanup; this doc
schedules it.

```ini
# /etc/systemd/system/dept-vacuumlo.service  (Phase 3b creates)
[Unit]
Description=DEPT large-object orphan cleanup
After=postgresql.service

[Service]
Type=oneshot
User=postgres
ExecStart=/usr/bin/vacuumlo -v codecoder

# /etc/systemd/system/dept-vacuumlo.timer
[Unit]
Description=Run vacuumlo nightly

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
```

Frequency: nightly. Empty-cost if no orphans. The 03 §7 trigger-based
`lo_unlink` on `media_assets` DELETE is the primary defence; this is the
belt-and-braces sweep.

### 6.5 `EXPLAIN` baselines for the hot queries

Phase 3b captures these into `tests/baseline/explain/` (one file per query). The
queries to baseline:

```sql
-- Q1: quiz generation, "questions the user hasn't seen"
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM questions
WHERE difficulty = 'intermediate'
  AND status = 'published'
  AND id NOT IN (...);                  -- quiz_generator.py:70-78

-- Q2: feed listing, published or flagged, newest first
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM feed_items
WHERE status IN ('published','flagged')
ORDER BY created_at DESC;               -- storage.py:370-376

-- Q3: attempt history for a user
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM attempts
WHERE user_email = $1
ORDER BY submitted_at DESC;             -- storage.py:191-196

-- Q4: verify-by-cert-id (single-row lookup; uses UNIQUE index)
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM attempts WHERE cert_id = $1;

-- Q5: in-flight quiz lookup
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM quiz_sessions WHERE quiz_id = $1;

-- Q6: count published questions per topic (topic_summary, main.py:162)
EXPLAIN (ANALYZE, BUFFERS)
SELECT topic, difficulty, count(*) FROM questions
WHERE status = 'published'
GROUP BY topic, difficulty;
```

Acceptable plans:

- Q1, Q2, Q3: **Index Scan**, not Seq Scan. If a plan flips to Seq Scan after
  a migration, the parity baseline catches it.
- Q4, Q5: **Index Only Scan** via the unique index.
- Q6: today this loads every row in Python (`quiz_generator.py:19-41`) — a
  v2 micro-fix is to push the aggregation into SQL (one row in cache for
  600s; `topic_summary` cache key).

---

## 7 · Front-end performance

### 7.1 Lazy-load non-current mode modules

`main.js:2-4` imports all three modes eagerly:

```js
import { renderScroll } from './modes/scroll.js';
import { renderRead } from './modes/read.js';
import { renderFeed } from './modes/feed.js';
```

In v2 (`frontend/modules/course/scroll.js` etc.), switch to dynamic import in
the router:

```js
// frontend/core/router.js (target shape)
const modes = {
  manual: () => import('../modules/course/scroll.js').then(m => m.renderScroll),
  read:   () => import('../modules/course/read.js').then(m => m.renderRead),
  feed:   () => import('../modules/feed/mode.js').then(m => m.renderFeed),
};
async function route() {
  const renderer = await modes[currentMode]();
  await renderer(view, ...);
}
```

Cost: ~1 extra round-trip on first mode switch (mitigated by HTTP/2 push
**not** being used — we trust HTTP/2 multiplexing). Saved: ~40-60KB of feed/read
code on every Manual-only visit.

### 7.2 Preload framework + first chapter

`<head>` in `frontend/index.html` (v2) gets:

```html
<link rel="preload" href="/api/course/framework" as="fetch" crossorigin>
<link rel="modulepreload" href="/app/js/core/api-client.js">
<link rel="modulepreload" href="/app/js/modules/course/scroll.js">
```

Reasoning: 80%+ of visitors land in Manual mode (the default route at
`main.js:86`); both the framework JSON and the scroll module are on the
critical path. `modulepreload` is HTTP/2-friendly and ETag-aware.

### 7.3 Conditional GET via `core/api-client.js`

`api-client.js` (01-blueprint.md:103) becomes the single fetch wrapper. It:

1. Keeps a `Map<url, etag>` per tab.
2. Sends `If-None-Match` on subsequent requests.
3. On `304`, returns the cached body from a parallel `Map<url, body>`.
4. **Stops setting `cache: 'no-cache'`** (the current `loadJSON`
   anti-pattern at `util/load.js:21`).

This makes `/api/course/framework` and `/api/course/chapters/*` essentially
free on warm tabs even when the server cache is empty — Apache's response is
a 60-byte `304` with the ETag header.

### 7.4 Media hints

The course HTML uses `<video src="../media/Anatomy of Code.mp4">` today
(`modes/scroll.js:21`). v2 serves the bytes from Postgres LO at
`/media/video/{asset_id}` (01 §1, MEDIA.md). Add:

- `preload="metadata"` on the `<video>` tag — don't preload bytes until play.
- For image-block media in feed cards, `<img loading="lazy" decoding="async">`.

Both are pure HTML attributes, no code changes beyond the renderer.

### 7.5 Bundle the framework + explainer into one round-trip (optional)

Currently three separate fetches at Manual mount:
`/api/course/framework`, `/api/course/framework-explainer`, then per-section
`/api/course/chapters/*`. A future optimisation is a single
`/api/course/bootstrap` endpoint that returns
`{framework, explainer, chapter_index}` in one payload. Cached as one entry.
Decision deferred — measure first (§8). Listed here so the option is on the
table.

---

## 8 · Measuring & observability

### 8.1 Performance smoke — `tests/baseline/perf/curl-smoke.sh`

A small bash script the parity harness owns. One run produces a fixture; later
runs compare timings within tolerance (e.g. ±25%).

```bash
#!/usr/bin/env bash
# tests/baseline/perf/curl-smoke.sh
# Baseline timings for the hot endpoints. Run after deploy; compare to the
# fixture under tests/baseline/perf/fixtures/<date>.txt.

set -euo pipefail
HOST="${1:-https://internal.in.deptagency.com}"
COOKIE="${COOKIE_JAR:-/tmp/dept.cookies}"

fmt='%{http_code} %{size_download} bytes  ttfb=%{time_starttransfer}s  total=%{time_total}s\n'

# Anonymous endpoints (no cookie).
curl -sS -o /dev/null -w "/anatomy/anatomy-of-code-course.html  $fmt" \
     "$HOST/anatomy/anatomy-of-code-course.html"
curl -sS -o /dev/null -w "/api/course/framework                  $fmt" \
     "$HOST/api/course/framework"
curl -sS -o /dev/null -w "/api/course/framework-explainer        $fmt" \
     "$HOST/api/course/framework-explainer"

# Conditional GET — should return 304 with ETag round-trip.
ETAG=$(curl -sS -D - -o /dev/null "$HOST/api/course/framework" | awk '/^etag:/ {print $2}' | tr -d '\r')
curl -sS -o /dev/null -w "/api/course/framework  cond            $fmt" \
     -H "If-None-Match: $ETAG" "$HOST/api/course/framework"

# Static asset — should hit Apache, not FastAPI; expect immutable Cache-Control.
curl -sS -o /dev/null -w "/app/js/main.js                        $fmt" \
     "$HOST/app/js/main.js"

# Compressed?
curl -sS -o /dev/null -w "compressed  $fmt" \
     -H "Accept-Encoding: gzip" -D - "$HOST/api/course/framework" \
     | awk '/content-encoding/ {print; exit}'

# Authenticated endpoints (cookie pre-loaded by a prior /login/dev call).
curl -sS -o /dev/null -w "/api/feed                              $fmt" \
     -b "$COOKIE" "$HOST/api/feed"
curl -sS -o /dev/null -w "/auth/me                               $fmt" \
     -b "$COOKIE" "$HOST/auth/me"
```

What it proves:

- `time_starttransfer` (TTFB) for `/api/course/*` drops to ~5ms warm-cache
  (vs ~25-50ms uncached today).
- `If-None-Match` returns `304` (not `200`).
- Static asset has `Cache-Control: public, max-age=31536000, immutable`.
- `Content-Encoding: gzip` is present on the JSON.

The fixture lives at `tests/baseline/perf/fixtures/` alongside the equivalence
fixtures (per `v2/02-parity-method.md` once written — coordinate with the
baseline agent).

### 8.2 Apache mod_status + `Server-Timing`

Enable `mod_status` bound to `127.0.0.1` (already loadable, no extra package):

```apache
<Location "/server-status">
    SetHandler server-status
    Require ip 127.0.0.1
    Require ip ::1
</Location>
```

For per-request timing visibility, the FastAPI app emits a `Server-Timing`
header from the cache layer:

```python
# core/cache.py contributes one timing
return JSONResponse(value, headers={
    "ETag": etag,
    "Server-Timing": f'cache;desc="{src}";dur={dur_ms:.1f}',
    "Cache-Control": "...",
})
```

Where `src ∈ {"hit", "miss", "etag-304"}`. Browsers' devtools surface this in
the network panel; no APM tool needed for the v2 launch.

### 8.3 APM later — defer

A real APM (OpenTelemetry → Honeycomb / Tempo / Sentry) is the right answer
once we have multi-VM topology. For v2 launch on a single VM with 2 workers,
`Server-Timing` + Postgres slow-query log + the curl smoke are sufficient.
Listed in Phase 5b backlog only.

---

## 9 · What Phase 3b implements — ordered checklist

Phase 3b (per `v2-plan.md:74`) executes the items below. Partitionable: items
in the same block can run in parallel; blocks are sequential.

**Block A — DB tuning (independent of Apache).**

1. **Write `infra/postgres/dept-anatomy.conf`** with the §6.1 values.
   `deploy.sh` `Include`s it via `psql -tAc 'SHOW config_file'` to find the
   active conf and appends the include line idempotently.
2. **Apply `db.py` pool config** (§6.2): `pool_size`, `max_overflow`,
   `pool_pre_ping`, `pool_recycle`. Add `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`
   to `core/config.py` (per 05).
3. **Confirm 03 §3 Alembic migrations carry the indexes** (§6.3 audit
   matrix). Cross-check on a freshly-created DB and on the production DB
   that was `alembic stamp`-baselined.
4. **Wire `vacuumlo` systemd timer** (§6.4). `deploy.sh` installs the
   `.service` + `.timer` unit files and enables the timer.

**Block B — App-layer cache (depends on Phase 1 module move so
`core/cache.py` exists).**

5. **Implement `core/cache.py`** (§4.1) — in-process LRU + ETag with TTL-only
   invalidation. No cross-worker broadcast in the default build; the seam
   is in place for Redis/LISTEN-NOTIFY later (§10 #1).
6. **Add `cached_response` dependency** and apply to:
   `/api/course/framework`, `/api/course/framework-explainer`,
   `/api/course/chapters/{filename}`, `/api/feed` (with the `feed:list:*`
   short TTL), `quiz_generator.topic_summary` consumers (cached at producer).
7. **Wire Directus webhook receiver in `modules/cms/routes.py`** to invalidate
   keys on the local worker (coordinates with 05-config-cms.md). The other
   worker(s) catch up at the next TTL boundary — accepted (§4.2).
   - `frameworks` write → `course:framework`, `course:framework-explainer`
   - `course_chapters` write → `course:chapters:list`, `course:chapter:*`
   - `questions` write → `quiz:topic_summary`
   - `app_config` write → `app_config:*`
8. **Replace `_active_quizzes` with `quiz_sessions` table reads/writes** (§5,
   03 §2.3). Delete the in-memory dict. Add the expiry-check + idempotent
   submit logic.

**Block C — Apache hardening.**

9. **Extend `a2enmod` loop in `deploy.sh:822`** to include
   `deflate expires http2 cache_socache socache_shmcb ratelimit` (§2.1).
   Add the `<Location "/api/media/upload">` rate-limit block at the same
   time (§2.1, owned by this doc per the 07 → 06 handoff).
10. **Add `Protocols h2 http/1.1`** to the `*:443` block (§2.2).
11. **Add `mod_deflate` configuration block** (§2.3).
12. **Add `Cache-Control` per-Location rules** (§2.4), de-duped against
    07-security-baseline's `Header always set` block.
13. **Implement `infra/cachebust.py`** and the `RewriteRule` for hashed-URL
    static (§3.1). Call it at the tail of `deploy.sh` Step 9, right after
    the `Apache vhost config` section completes and before the
    `apache2ctl -t` validation.

**Block D — Front-end perf.**

14. **`core/api-client.js`** with ETag/If-None-Match support (§7.3, 01).
15. **Lazy-import modes from `core/router.js`** (§7.1).
16. **Add `<link rel="preload">` and `<link rel="modulepreload">` in
    `frontend/index.html`** (§7.2).
17. **Remove `cache: 'no-cache'`** from the `loadJSON` migration path
    (`util/load.js:21` → new `api-client.js`; the old function is removed
    when its callers are migrated in Phase 1).

**Block E — Verification.**

18. **Author and check in `tests/baseline/perf/curl-smoke.sh`** + a first
    fixture (§8.1).
19. **Capture EXPLAIN baselines for §6.5 queries** into
    `tests/baseline/explain/`.
20. **Run parity harness** (per 02-parity-method.md once written) and
    confirm no regression on any cached endpoint.

---

## 10 · Open gate decisions — defaults so the user can flip them

These are explicit so the Phase 0 gate can answer yes/no on each.

### Decision 1 — App-cache backend & invalidation strategy

**Default: in-process LRU + TTL-only invalidation** (§4.2). Single VM,
2 workers, no new infra. Local-worker `cache.invalidate(prefix)` calls run
synchronously inside the webhook handler; other workers catch up at the
TTL boundary (15 min framework, 30 s feed, 60 s app_config — all bounded
small enough that the staleness window is acceptable for an editor-driven
practice site).

**Alternative A: in-process LRU + Postgres `LISTEN/NOTIFY` broadcast.**
Each worker spawns a listener task on startup; the CMS webhook issues
`NOTIFY cache_invalidate, 'framework'` and all workers invalidate
immediately. Real complexity cost: requires a sync `psycopg2` driver
alongside the async SQLAlchemy stack (or `asyncpg` with its own connection
lifecycle), an async reconnect loop that survives Postgres restarts, the
~8 KB `NOTIFY` payload cap, and a clear listener-thread shutdown path on
uvicorn worker reload. Adds ~80-100 lines, two failure modes, and one
extra runtime dependency — for a problem that affects two workers for
worst-case 15 minutes. Park here unless the default's staleness window
shows up as a real editor complaint.

**Alternative B: Redis from day 1.** Cleaner cross-worker semantics; one
more service to install, secure, monitor. Right answer if we plan to land
4+ workers soon or a second VM. The `core/cache.py` seam (§4.1) is
identical either way.

**Flip to A if:** Phase 3b operator feedback shows the 15-minute worker-2
staleness window is too long for editors but the workload is still under
2 workers on 1 VM.

**Flip to B if:** worker count grows to 4+, or we add a second VM, or
Phase 3b shows >20% cache-coherency-related staleness even after enabling
LISTEN/NOTIFY.

### Decision 2 — Brotli: ship now vs defer

**Default: defer.** Ship `mod_deflate` only at v2 launch (§2.6). Evaluate
Brotli after the first month with real Server-Timing data.

**Alternative: enable mod_brotli at v2 launch.** ~15-25% size win on
text/JSON; requires extra package install in `deploy.sh` (Debian:
`libapache2-mod-brotli`; RHEL: EPEL) and ~50% more CPU per response.

**Flip if:** the FE bandwidth profile under HTTP/2 + gzip is still the slow
link.

### Decision 3 — Cache-bust mechanism for the buildless FE

**Default: mod_rewrite hashed-prefix URL** (`/app/js/v=<hash>/main.js`)
combined with `infra/cachebust.py` rewriting only the deployed `index.html`
(§3.1). Source files untouched, deploy stays idempotent, rollback safe.

**Alternative: rename-on-deploy** (`main.js → main.<hash>.js` plus
import-graph rewrite). No Apache rewrite rule. Slightly more deploy
complexity; same caching properties.

**Flip if:** the Apache rewrite rule adds visible friction in dev (e.g.
breaks the `start_local.sh` no-Apache flow). Both options are similar
effort; current recommendation is mod_rewrite for the stateless property.

### Decision 4 — Quiz session storage

**Default: Postgres `quiz_sessions` table** (§5, 03 §2.3). Atomic with the
attempts insert; no new infra; trivial volume.

**Alternative: Redis with TTL.** Faster (sub-100μs) and self-expiring; loses
the transactional atomicity with `attempts`, and only worth it if we hit
Redis-level scale.

**Flip if:** Decision 1 picks Redis. Then sessions can live there too. But
even then, the atomicity argument for keeping them in Postgres is strong.

### Decision 5 — TTL for `/api/feed`

**Default: 30 seconds, with ETag.** Feed is UGC; "near-real-time" is the
right product behaviour. Short TTL + ETag means an active reader feels
fresh; idle tabs are still cheap on the server.

**Alternative: no TTL at all (cache only the structure, recompute the
freshness ordering per request)**. Simpler invalidation; every request hits
DB. Acceptable if traffic is low.

**Flip if:** measurement at §8.1 shows feed latency is fine without the
cache.

### Decision 6 — `topic_summary` SQL aggregation

**Default: keep the Python aggregation** (`quiz_generator.py:19-41`) but
cache the **result** (key `quiz:topic_summary`, TTL 600s, invalidated on
question writes) — §4.3. Zero migration risk.

**Alternative: rewrite as a SQL `GROUP BY`** (one row per topic/difficulty)
and cache that. Faster on cold cache; slightly more code change.

**Flip if:** the cold-cache miss latency on `topic_summary` measured in §8.1
is above ~50ms.

---

## 11 · Cross-references summary

| This doc § | References |
|---|---|
| §1.3 in-memory dict | 03-data-model §2.3 (`quiz_sessions` design) |
| §1.7 index drift | 03-data-model §1.9.2, §2.8, §3 (Alembic carries them) |
| §2.4 Cache-Control + §2.5 headers | 07-security-baseline (dedupe `Header always set`) |
| §3.1 cache-bust | 01-blueprint §1 (`frontend/index.html`, deploy step) |
| §4.1 `core/cache.py` seam | 01-blueprint §1.core/cache.py |
| §4.3 invalidation triggers | 05-config-cms (Directus webhooks) |
| §5 quiz sessions | 03 §2.3 verbatim |
| §6.1 PG conf | 03-data-model.md general; 04 cookie security has no overlap |
| §6.2 pool | 05-config-cms §1.5 (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW` env registry); this doc owns the values |
| §6.3 index audit | 03 §2.8 + §3 |
| §6.4 vacuumlo | 03 §7 (LO lifecycle), 07 (security) |
| §7 FE perf | 01-blueprint §1 (`core/api-client.js`, `core/router.js`) |
| §10 gate decisions | v2-plan.md §"Open decisions" (these add four more) |
