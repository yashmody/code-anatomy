---
id: apis
title: API reference
sidebar_position: 6
---

# API reference

The complete HTTP surface of the FastAPI application, grouped by module. Every
endpoint lives in `backend/app/modules/<name>/routes.py`; the composition root
that mounts them is `backend/app/main.py`. The route map there is the canonical
list — this page is the reader-friendly view.

## Scan box

- **One application, many routers.** `main.py` includes one router per module
  under a stable prefix. Paths are preserved from the legacy monolith so issued
  certificates keep verifying and the SPA keeps fetching the same URLs.
- **Auth is cookie-session.** Browser endpoints use the `aoc_session` cookie;
  protected routes are gated by `require_permission(...)` (see
  [Users & roles](../admin/users-and-roles)).
- **Read endpoints are cache-backed.** `/api/course/*`, `/api/feed`,
  `/api/faqs`, `/api/runbooks` read through the app cache; Directus busts the
  relevant key via the loopback webhook.
- **Health probes are unauthenticated.** `/healthz`, `/readyz`, `/csp/report`
  never redirect and have no module dependencies.
- **Some payloads are encrypted on the wire.** The quiz start/submit bodies are
  AES-GCM encrypted; that is transport hardening, not the security boundary.

## Health (unauthenticated)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness — `{status, version, env}`, no dependency checks |
| GET | `/readyz` | Readiness — `200` if DB (and Redis if selected) reachable, else `503` |
| POST | `/csp/report` | CSP violation sink — logs and returns `204` |

## Auth

| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/session-key` | Public key material for payload encryption |
| GET/POST | `/login`, `/login/dev` | Dev email login (development only) |
| GET | `/auth/google` | Start Google SSO (PKCE + nonce) |
| GET | `/auth/google/callback` | OAuth callback — verifies id_token + domain, opens session |
| GET | `/logout` | Clear the session |
| GET | `/auth/me` | `{email, persona, roles, permissions}` — drives SPA gating |

## Quiz (mounted at root)

| Method | Path | Permission |
|---|---|---|
| GET | `/` | Home (Jinja) |
| GET/POST | `/onboarding/role`, `/profile/role` | — (persona, non-authorising) |
| GET | `/quiz/take` | renders the exam page |
| POST | `/quiz/start` | samples 30 questions, opens server-side state |
| POST | `/quiz/submit` | grades, signs, mints + emails certificate |
| GET | `/certificate/{cert_id}` | streams the PDF to its owner |
| GET | `/history` | the signed-in user's attempts |
| GET | `/verify`, `/verify/{cert_id}` | **public** certificate verification |
| GET | `/admin/attempts` | `attempts.view_all` |
| POST | `/api/admin/questions` | `question.write` |

## Course content (prefix `/api/course`)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/course/framework` | Framework spine |
| GET | `/api/course/framework-explainer` | Framework explainer |
| GET | `/api/course/chapters` | Chapter list (cached) |
| GET | `/api/course/chapters/{filename}` | One chapter's block tree (cached) |

## Feed (prefix `/api`)

| Method | Path | Permission |
|---|---|---|
| GET | `/api/feed` | — (published items, cached ~30s) |
| POST | `/api/feed` | `feed.create` |
| POST | `/api/feed/flag` | `feed.flag` |
| GET | `/api/moderate/queue` | `moderate.view` |
| POST | `/api/moderate/action` | `moderate.action` |

## Media

| Method | Path | Permission |
|---|---|---|
| POST | `/api/media/upload` | `media.upload` — multipart, validated, → Postgres large object |
| GET | `/media/video/{asset_id}` | — streams with HTTP Range |
| GET | `/media/image/{asset_id}` | — serves from large object |

## FAQs (prefix `/api/faqs`)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/faqs` | Categories with question counts (cached) |
| GET | `/api/faqs/{category_id}` | Category detail + items (cached) |

## Runbooks (prefix `/api/runbooks`)

| Method | Path | Permission |
|---|---|---|
| GET | `/api/runbooks/template` | — downloads the blank `.xlsx` template |
| GET | `/api/runbooks` | — published list |
| GET | `/api/runbooks/all` | `content.write` — incl. drafts |
| GET | `/api/runbooks/{slug}` | — one runbook (drafts need `content.write`) |
| POST | `/api/runbooks/upload` | `content.write` — `.xlsx` ingest (`?publish=`) |
| POST | `/api/runbooks/json` | `content.write` — JSON upsert |
| DELETE | `/api/runbooks/{slug}` | `content.write` |

## CMS, What's New, admin

| Method | Path | Notes |
|---|---|---|
| POST | `/api/cms/webhook` | **loopback only** — cache invalidation from Directus |
| GET | `/api/whatsnew` | the What's New feed |
| GET/POST/DELETE | `/api/admin/roles` | `role.assign` (platform_admin) |

:::note[Agency Tip]

The authoritative endpoint list is the docstring route-map at the top of
`backend/app/main.py`, kept in sync with the `include_router(...)` calls below
it. When you add a module, add its router there under a stable prefix — and if it
introduces a protected route, add the permission to `PERMISSION_GRANTS` first
(see [Users & roles](../admin/users-and-roles)).

:::

:::caution[Common Pitfall]

`/api/cms/webhook` is **not** a public integration point. It is bound to
loopback, guarded by Apache `Require ip 127.0.0.1`, and rejected by the handler
for non-loopback callers. Only the co-resident Directus can call it. Do not build
external automation against it.

:::

For how the read endpoints are cached and invalidated, see
[caching & performance](./architecture/caching-performance) and
[the Directus write plane](./data-model/directus-write-plane).
