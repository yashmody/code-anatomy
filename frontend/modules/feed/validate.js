// feed/validate.js — the ONE feed-item validator. Used by BOTH the composer (for
// inline field errors) and store.createPost (the defensive data-layer gate). One
// contract, two callers.
//
// THE CONTRACT is content-architecture/schemas/feed.schema.json (JSON Schema, draft
// 2020-12). The SAME schema the server will re-validate against in the backend pass —
// the client gate is a courtesy, not the authority. We never loosen it here.
//
// HOW IT VALIDATES — two paths, same {ok, errors} shape so callers don't care which ran:
//   PRIMARY  — lazy-import Ajv 2020-12 + ajv-formats from a CDN (ES modules), fetch the
//              real schema once, compile once (cached), validate. This is the true
//              draft-2020-12 check, including the allOf if/then per-type required fields,
//              the media $defs, the id pattern, the date-time formats, the engagement ints.
//   FALLBACK — if the CDN import fails (offline / blocked / CSP), a hand-rolled check of
//              the schema's CORE so the gate still works. Logs ONE console.warn. It is
//              intentionally close to the schema but not a full re-implementation.
//
// PLUS one rule the schema can't express but validate.py enforces: a `post` body must be
// ≤ 100 words (split on whitespace). We mirror validate.py exactly so the composer's
// preview matches the real CI gate. This rule runs in BOTH paths.

import { getFeedBase } from './store.js';

// CDN ES-module endpoints. Ajv's 2020 build is the draft-2020-12 entry point.
//
// SRI note (07 §3.3 / F-SUP-02): these are loaded via dynamic `import()`, not a
// <script> tag, so they CANNOT carry an `integrity` attribute — subresource
// integrity for ES modules needs an import map `integrity` field (not yet
// broadly supported) or a `<link rel=modulepreload integrity>`, neither of
// which this lazy loader uses. The hardening we CAN apply is exact version
// pinning: esm.sh's pinned `@8.17.1` / `@3.0.1` URLs are immutable, so the
// resolved artefact can't silently drift under us. The CSP `script-src`
// allow-list (07 §3.2, Apache-owned) restricts these imports to `esm.sh`
// alone — that is the real supply-chain gate for the module path. If a future
// loader switches to a <link rel=modulepreload>, compute the hashes with:
//   curl -fsSL https://esm.sh/ajv@8.17.1/dist/2020.js \
//     | openssl dgst -sha384 -binary | openssl base64 -A
// (note esm.sh varies the entry module by target/User-Agent, so pin the
//  resolved /denonext/... artefact, not the redirecting entry URL).
const AJV_2020_URL = 'https://esm.sh/ajv@8.17.1/dist/2020.js';
const AJV_FORMATS_URL = 'https://esm.sh/ajv-formats@3.0.1';

// Module-level caches: compile the schema exactly once across the app's lifetime.
let _validatorPromise = null; // Promise<(item)=>boolean> | null  — the compiled Ajv validate fn
let _usingFallback = false;   // set true once we've fallen back, so we don't retry the CDN

// validate.py's extra rule, mirrored: a post body over 100 words is rejected. Returns an
// error object, or null if fine. Whitespace split matches Python's str.split().
function postWordCountError(item) {
  if (!item || item.type !== 'post') return null;
  const words = String(item.body == null ? '' : item.body).split(/\s+/).filter(Boolean);
  if (words.length > 100) {
    return { path: '/body', message: `Post body is ${words.length} words (max 100).` };
  }
  return null;
}

// Lazily build (and cache) the Ajv-backed validate function. Resolves to the compiled
// validator, or null if the CDN path is unavailable (caller then uses the fallback).
async function getAjvValidator() {
  if (_usingFallback) return null;
  if (_validatorPromise) return _validatorPromise;

  _validatorPromise = (async () => {
    // Dynamic imports — only fetched the first time a validation is actually requested.
    const ajvMod = await import(/* @vite-ignore */ AJV_2020_URL);
    const formatsMod = await import(/* @vite-ignore */ AJV_FORMATS_URL);
    const Ajv2020 = ajvMod.default || ajvMod.Ajv2020 || ajvMod;
    const addFormats = formatsMod.default || formatsMod;

    const base = getFeedBase();
    const res = await fetch(`${base}/schemas/feed.schema.json`);
    if (!res.ok) throw new Error(`Could not fetch feed.schema.json (${res.status}).`);
    const schema = await res.json();

    const ajv = new Ajv2020({ allErrors: true, strict: false });
    addFormats(ajv);
    return ajv.compile(schema);
  })().catch((err) => {
    // CDN blocked / offline / fetch failed — fall back, once, loudly but not fatally.
    console.warn(
      'feed/validate: strict schema validation unavailable (CDN import failed) — ' +
      'falling back to the lightweight check. Reason:', err && err.message ? err.message : err
    );
    _usingFallback = true;
    _validatorPromise = null;
    return null;
  });

  return _validatorPromise;
}

// Humanise a validator path into a clean, capitalised field label. Strips the leading
// slash, takes the last non-numeric segment (so "/items/0/text" → "Text"), splits camelCase
// ("userId" → "User id"), and capitalises the first letter. Empty path → "This field".
function fieldLabel(path) {
  if (!path) return 'This field';
  const segs = String(path).split('/').filter((s) => s && !/^\d+$/.test(s));
  const last = segs.length ? segs[segs.length - 1] : '';
  if (!last) return 'This field';
  const spaced = last.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// Compose one clean, humanised line: "<Field> <constraint>." — field named exactly once,
// no leading slash, no doubling, single trailing full stop.
function humanError(path, constraint) {
  const text = `${fieldLabel(path)} ${constraint}`.trim().replace(/\s+/g, ' ');
  return /[.!?]$/.test(text) ? text : text + '.';
}

// Map one Ajv error to our { path, message } shape. Prefer the instance path; fall back
// to the schema path. The human message is built by humanError() so it matches the
// fallback path's phrasing exactly (capitalised field, named once, no slash).
function mapAjvError(e) {
  // Prefer the instance path. For a `required` error Ajv reports the *schema* path
  // (e.g. "#/allOf/3/then/required") and names the missing field in params — we surface
  // that field as the path ("/<field>") so the composer can mark the offending input.
  let path = e.instancePath || '';
  let constraint = e.message || 'is invalid';
  if (e.keyword === 'required' && e.params && e.params.missingProperty) {
    path = (e.instancePath || '') + '/' + e.params.missingProperty;
    constraint = 'is required';
  } else if (e.keyword === 'enum' && e.params && e.params.allowedValues) {
    constraint = `must be one of: ${e.params.allowedValues.join(', ')}`;
  } else if (e.keyword === 'pattern' && e.params && e.params.pattern) {
    constraint = `does not match the required pattern ${e.params.pattern}`;
  } else if (e.keyword === 'minItems' && e.params && e.params.limit != null) {
    constraint = `must have at least ${e.params.limit} entries`;
  } else if (!path) {
    // a non-required error with no instance path — fall back to the schema path so the
    // summary still reads sensibly (these are rare given the schema's shape).
    path = e.schemaPath || '';
  }
  return { path, message: humanError(path, constraint) };
}

// ── PUBLIC: validate one feed item ───────────────────────────────────────────────
// Returns { ok: boolean, errors: [{ path, message }] }. Always resolves (never throws);
// a thrown internal error is itself reported as a single error so callers stay simple.
export async function validateFeedItem(item) {
  try {
    const validate = await getAjvValidator();
    if (validate) {
      const ok = validate(item);
      // Drop Ajv's structural `if` echo: an allOf if/then per-type block emits a contentless
      // `if` error ("must match then schema") alongside the REAL error inside the `then`
      // branch (the required/type one we actually surface). Filtering it leaves the single
      // readable, field-named sentence — and never changes pass/fail (the real error stays).
      const errors = ok ? [] : (validate.errors || []).filter((e) => e.keyword !== 'if').map(mapAjvError);
      // The post word-count rule is NOT in the schema — apply it on top, both paths.
      const wc = postWordCountError(item);
      if (wc) { errors.push(wc); }
      return { ok: errors.length === 0, errors };
    }
  } catch (err) {
    // Unexpected — record it and continue to the fallback so we still return a verdict.
    console.warn('feed/validate: Ajv validation threw, using fallback.', err);
  }
  return fallbackValidate(item);
}

// ── FALLBACK: hand-rolled core check ─────────────────────────────────────────────
// Covers the schema's load-bearing rules: id pattern, type enum, author.userId+name,
// status enum, topics array, createdAt/updatedAt present, engagement integer triple,
// frameworkRef pattern (when present), per-type required payload fields, media kind/
// render shape, AND the ≤100-word post rule. Not a full schema re-implementation —
// just enough that a malformed item never slips through when the CDN is unreachable.
const TYPE_ENUM = ['post', 'video', 'list', 'card', 'vocab', 'scenario'];
const STATUS_ENUM = ['draft', 'pending-review', 'published', 'flagged', 'removed'];
const ID_RE = /^post\.[a-z0-9]+$/;
const REF_RE = /^[a-z]+(\.[a-z0-9]+){1,3}$/;

function isInt(n) { return typeof n === 'number' && Number.isInteger(n); }
function isStr(s) { return typeof s === 'string'; }

function fallbackValidate(item) {
  const errors = [];
  // Humanise like mapAjvError: capitalise the field (from the path), name it once, no slash.
  const add = (path, constraint) => errors.push({ path, message: humanError(path, constraint) });

  if (!item || typeof item !== 'object') {
    return { ok: false, errors: [{ path: '', message: 'Item must be an object.' }] };
  }

  // ── envelope ──
  if (!isStr(item.id) || !ID_RE.test(item.id)) add('/id', 'must match ^post.[a-z0-9]+$');
  if (!TYPE_ENUM.includes(item.type)) add('/type', `must be one of: ${TYPE_ENUM.join(', ')}`);

  const a = item.author;
  if (!a || typeof a !== 'object') add('/author', 'is required');
  else {
    if (!isStr(a.userId) || !a.userId) add('/author/userId', 'is required');
    if (!isStr(a.name) || !a.name) add('/author/name', 'is required');
    if (a.initials != null && (!isStr(a.initials) || a.initials.length > 3)) add('/author/initials', 'must be ≤ 3 characters');
  }

  if (!STATUS_ENUM.includes(item.status)) add('/status', `must be one of: ${STATUS_ENUM.join(', ')}`);
  if (!Array.isArray(item.topics)) add('/topics', 'must be an array');
  if (item.frameworkRef != null && (!isStr(item.frameworkRef) || !REF_RE.test(item.frameworkRef))) {
    add('/frameworkRef', 'does not match the framework address pattern');
  }
  if (!isStr(item.createdAt) || !item.createdAt) add('/createdAt', 'is required');
  if (!isStr(item.updatedAt) || !item.updatedAt) add('/updatedAt', 'is required');

  const e = item.engagement;
  if (!e || typeof e !== 'object') add('/engagement', 'is required');
  else {
    if (!isInt(e.upvotes) || e.upvotes < 0) add('/engagement/upvotes', 'must be an integer ≥ 0');
    if (!isInt(e.comments) || e.comments < 0) add('/engagement/comments', 'must be an integer ≥ 0');
    if (!isInt(e.saves) || e.saves < 0) add('/engagement/saves', 'must be an integer ≥ 0');
  }

  // ── per-type payload (mirrors the schema's allOf if/then required fields) ──
  switch (item.type) {
    case 'post':
      if (!isStr(item.body)) add('/body', 'is required');
      if (item.title != null && !isStr(item.title)) add('/title', 'must be a string');
      break;
    case 'video':
      if (!isStr(item.title) || !item.title) add('/title', 'is required');
      if (!isInt(item.durationSec) || item.durationSec < 1) add('/durationSec', 'must be an integer ≥ 1');
      if (item.hook != null && !isStr(item.hook)) add('/hook', 'must be a string');
      if (item.url != null && !isStr(item.url)) add('/url', 'must be a string');
      if (item.videoAssetId != null && !isStr(item.videoAssetId)) add('/videoAssetId', 'must be a string');
      break;
    case 'list':
      if (!isStr(item.title) || !item.title) add('/title', 'is required');
      if (!Array.isArray(item.items) || item.items.length < 1) add('/items', 'must have at least one row');
      else item.items.forEach((row, i) => {
        if (!row || typeof row !== 'object' || !isStr(row.text) || !row.text) add(`/items/${i}/text`, 'is required');
      });
      break;
    case 'card':
      if (!isStr(item.title) || !item.title) add('/title', 'is required');
      if (!isStr(item.teaser) || !item.teaser) add('/teaser', 'is required');
      break;
    case 'vocab':
      if (!isStr(item.term) || !item.term) add('/term', 'is required');
      if (!isStr(item.definition) || !item.definition) add('/definition', 'is required');
      break;
    case 'scenario':
      if (!isStr(item.prompt) || !item.prompt) add('/prompt', 'is required');
      if (!Array.isArray(item.options) || item.options.length < 2) add('/options', 'must have at least 2 entries');
      else if (!item.options.every(isStr)) add('/options', 'must contain only text entries');
      if (!isInt(item.correct) || item.correct < 0) add('/correct', 'must be an integer ≥ 0');
      if (!isStr(item.verdict) || !item.verdict) add('/verdict', 'is required');
      if (!isStr(item.reveal) || !item.reveal) add('/reveal', 'is required');
      break;
    default:
      break; // type error already recorded above
  }

  // ── media (optional; when present each item must match the kind shape) ──
  if (item.media != null) {
    if (!Array.isArray(item.media)) add('/media', 'must be an array');
    else item.media.forEach((m, i) => {
      const p = `/media/${i}`;
      if (!m || typeof m !== 'object') { add(p, 'must be an object'); return; }
      if (m.kind !== 'image' && m.kind !== 'diagram') { add(`${p}/kind`, 'must be "image" or "diagram"'); return; }
      if (m.kind === 'image') {
        if (!isStr(m.url) || !m.url) add(`${p}/url`, 'is required for an image');
      } else {
        if (!['mermaid', 'ascii', 'image'].includes(m.render)) add(`${p}/render`, 'must be mermaid, ascii or image');
      }
    });
  }

  // ── the extra validate.py rule ──
  const wc = postWordCountError(item);
  if (wc) errors.push(wc);

  return { ok: errors.length === 0, errors };
}
