// Centralised front-end configuration.
//
// One place to change runtime constants — every other module imports from
// here. Values are derived from window.location so the same build runs in
// dev (python -m http.server) and in prod (Apache reverse-proxy at /).
//
// Phase 2d (config CMS) will turn ALLOWED_DOMAIN into a DB-config read;
// today it's still a literal — kept here so the upgrade is one edit.

// API_BASE — empty string means "same origin as the FE". Apache routes
// everything that isn't a static FE asset to FastAPI, so '' is the right
// production default. Override at runtime via window.__API_BASE for
// experiments without rebuilding.
export const API_BASE =
  (typeof window !== 'undefined' && window.__API_BASE) ||
  // Local dev: static server on :8080 can't proxy /api/ — route to FastAPI on :8000.
  (typeof location !== 'undefined' && location.port === '8080'
    ? 'http://127.0.0.1:8000'
    : '');

// QUIZ_URL — in production the FastAPI quiz app is reverse-proxied at the
// same origin as this SPA. In local dev (file:// or python -m http.server
// on a different port), fall back to localhost:8000 where the quiz
// typically runs.
export const QUIZ_URL =
  (typeof location !== 'undefined' &&
   (location.protocol === 'http:' || location.protocol === 'https:'))
    ? `${location.origin}/`
    : 'http://localhost:8000/';   // dev fallback ONLY (file://)

// Stable media aliases. The MP4 lives in Postgres as a large object and
// each environment has its own asset_id UUID — the FE can't hold UUIDs.
// MEDIA.explainer is a server-side alias that resolves slug='explainer'
// to the active media_assets row and Range-streams it. See 01-blueprint
// §7.1 MP4-delivery contract.
export const MEDIA = {
  explainer: '/media/video/explainer'
};

// The ordered list of chapter JSONs the Manual reads. Order is not
// authoritative — framework.json controls display order — but every file
// the Manual will ever load is enumerated here so Contents and the
// Manual can agree on what exists without a directory listing.
export const SECTION_FILES = [
  'code-c.json', 'code-o.json', 'code-d.json', 'code-e.json',
  'coder-c.json', 'coder-o.json', 'coder-d.json', 'coder-e.json', 'coder-r.json',
  'anatomy-m00.json', 'anatomy-m01.json', 'anatomy-m01b.json',
  'anatomy-m02.json', 'anatomy-m02b.json', 'anatomy-m03.json',
  'anatomy-m04.json', 'anatomy-m05.json', 'anatomy-m06.json',
  'anatomy-m07.json', 'anatomy-m08.json', 'anatomy-m09.json', 'anatomy-m10.json',
  'adobe-cm.json', 'adobe-aa.json', 'adobe-cja.json', 'adobe-ajo.json', 'adobe-camp.json',
  'adobe-csc.json', 'adobe-ab.json',
  'ai-bmad.json', 'ai-gov.json'
];

// CONTENT_BASE — base path for frozen content pages (FAQs, Checklist, Runbooks).
// Apache aliases /anatomy/ → content/frozen/ in production (same origin).
// In local dev (port 8080, Python static server from repo root) there is no
// /anatomy/ alias — the files sit at /content/frozen/ instead.
export const CONTENT_BASE =
  (typeof location !== 'undefined' && location.port === '8080')
    ? '/content/frozen'
    : '/anatomy';

// localStorage keys. One file owns these so renames don't drop a user's
// theme on the floor.
export const THEME_KEY = 'anatomy-app-theme';

// Auth domain allow-list. Phase 2d makes this a DB-config read.
export const ALLOWED_DOMAIN = 'deptagency.com';

// Google sign-in client id. Empty disables Google sign-in (the FE shows
// the dev sign-in fallback when DEV_MOCK is true). Set per env later via
// a build-time inject or window.__GOOGLE_CLIENT_ID override.
export const GOOGLE_CLIENT_ID =
  (typeof window !== 'undefined' && window.__GOOGLE_CLIENT_ID) || '';

// Dev mock toggle. When true, the Feed shows a "Dev sign-in" button that
// signs in as dev@<ALLOWED_DOMAIN>. Off in production.
export const DEV_MOCK = true;
