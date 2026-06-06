# directus-extension-media-upload

A Directus **module** (full-page admin screen) for uploading app media. It is a
thin client of the FastAPI media pipeline — **no bytes are ever written to
Directus storage or the filesystem**.

- **Upload tab** — file picker + drag-drop. POSTs the file as
  `multipart/form-data` (field name `file`) to FastAPI `POST /api/media/upload`,
  which validates it, writes the bytes to a Postgres large object, inserts a
  `media_assets` row, and returns the asset id. Shows progress, the returned id,
  and a preview from `GET /media/{image,video}/{id}`.
- **Browse tab** — lists existing `media_assets` via the Directus items API
  (read-only metadata) and previews bytes from FastAPI `/media/*`.

This upholds Phase 0 decision C: app media lives only in Postgres large objects,
streamed by FastAPI. See `docs/architecture/v2/05-config-cms.md` and
`cms/README.md` ("Media storage").

## Auth (no new auth surface)

The upload reuses the learner-plane session cookie `aoc_session` + the
`media.upload` permission (granted to `content_author` / `feed_contributor`).

- **Prod** — Apache serves Directus (`/cms/`) and FastAPI (`/`) on one origin, so
  the upload uses a **relative** URL and the cookie rides along. Leave the
  "FastAPI base URL" field blank.
- **Dev** — Directus (`:8055`) and FastAPI (`:8000`) are different origins. Set
  the base URL to `http://localhost:8000`, ensure the backend `CORS_ORIGINS`
  includes `http://localhost:8055`, and be signed into the app in the same
  browser as a user holding `media.upload`.

## Build (node@22 only)

The repo's default Node 25 cannot build Directus (see `cms/README.md`). Use the
Homebrew node@22 toolchain:

```bash
export PATH=/usr/local/opt/node@22/bin:$PATH
cd cms/extensions/directus-extension-media-upload
npm install          # build-time devDeps only (gitignored)
npm run build        # -> dist/index.js  (committed)
```

`dist/` is committed so both deploy shapes (docker bind-mount + npm/systemd) load
the module with no deploy-time build. The module is enabled in the Directus
module bar idempotently by `cms/register-collections.mjs`
(`ensureModuleEnabled()`), run via `bash cms/bootstrap.sh`.
