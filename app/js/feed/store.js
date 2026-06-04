// feedStore — the feed data layer. THE SEAM.
//
// This is a CLIENT-SIDE seam. Persistence here is per-browser (localStorage),
// NOT shared across users: a post you create, or a flag you raise, lives only in
// the browser that did it. Cross-user flagging and a shared post store need the
// backend pass — they cannot work from localStorage.
//
// This module is the ONLY place localStorage is read/written for feed data.
// No other file may touch localStorage for the feed. When Postgres arrives, the
// backend swap is: re-implement THIS module's functions as HTTP calls. The UI does
// not move — it already speaks only to these functions, never to storage directly.
//
// Storage layout — one namespace prefix `feedStore.` so it is trivial to clear:
//   feedStore.userPosts → Post[]  created in this browser            (empty until Step 5)
//   feedStore.flags     → { [postId]: { flagCount, status } } overlay (empty until Step 6)
//   feedStore.session   → current session object                     (set in Step 4)

import { loadJSON } from '../util/load.js';
import { loadFramework, indexFramework } from '../util/framework.js';
import { validateFeedItem } from './validate.js';

// One flag marks a post by default. Retune here, in one place.
export const FLAG_THRESHOLD = 1;

// Where the content-architecture data package lives, relative to app/. Matches the
// BASE main.js passes into the modes. The mode calls configureFeedStore(base) once
// before reading; the default keeps the store usable if that call is ever skipped.
let BASE = '../content-architecture';
export function configureFeedStore(base) {
  if (base) BASE = base;
}
// The base seam, read-only. feed/validate.js fetches feed.schema.json relative to
// this so the validator always points at the same data package the store reads.
export function getFeedBase() {
  return BASE;
}

// ── storage keys ────────────────────────────────────────────────────────────
const K_USER_POSTS = 'feedStore.userPosts';
const K_FLAGS = 'feedStore.flags';
const K_SESSION = 'feedStore.session';

// ── safe localStorage + JSON wrappers (private mode, quota, malformed data) ───
function safeParse(str, fallback) {
  if (str == null) return fallback;
  try { return JSON.parse(str); } catch (e) { return fallback; }
}
function lsGet(key, fallback) {
  try { return safeParse(localStorage.getItem(key), fallback); }
  catch (e) { return fallback; }
}
function lsSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch (e) { console.warn('feedStore: could not write', key, e); return false; }
}

// ── module-level caches (the seed + framework are read-only, fetched once) ────
let _seedPromise = null;     // Promise<Post[]> — the seed feed, cached after first load
let _seedSync = null;        // the resolved seed array, for sync reads (flagPost fallback)
let _categoriesPromise = null; // Promise<Category[]> — derived from framework.json

async function loadSeed() {
  if (!_seedPromise) {
    _seedPromise = loadJSON(`${BASE}/feed/feed.json`).then((data) => {
      const arr = Array.isArray(data) ? data : (data.feed || []);
      _seedSync = arr;
      return arr;
    });
  }
  return _seedPromise;
}

// ── session (writes used by Step 4; reads used now to gate compose/flag UI) ───
export function getSession() {
  return lsGet(K_SESSION, null);
}
export function setSession(session) {
  lsSet(K_SESSION, session);
}
export function clearSession() {
  try { localStorage.removeItem(K_SESSION); } catch (e) { /* ignore */ }
}

// ── flags overlay ─────────────────────────────────────────────────────────────
function readFlags() {
  const o = lsGet(K_FLAGS, {});
  return (o && typeof o === 'object') ? o : {};
}
function readUserPosts() {
  const a = lsGet(K_USER_POSTS, []);
  return Array.isArray(a) ? a : [];
}

// Apply the per-browser flags overlay onto a post. Returns a fresh object so the
// cached seed is never mutated. If an override exists for this id, its flagCount
// and status win over the seed values.
function applyOverlay(post, flags) {
  const ov = flags[post.id];
  if (!ov) return { ...post };
  const next = { ...post, status: ov.status || post.status };
  next.moderation = { ...(post.moderation || {}), flagCount: ov.flagCount };
  return next;
}

// ── framework-driven categories ──────────────────────────────────────────────
// Built from framework.json, NOT hardcoded. Emits CODE letters then CODER letters
// in framework order, plus a trailing "other" bucket. Anatomy/Adobe/AI rings are
// intentionally skipped for the chip row; the "other" bucket still catches any
// frameworkRef that does not resolve to a chip, so nothing is lost.
const CATEGORY_RINGS = ['code', 'coder'];

async function buildCategories() {
  if (!_categoriesPromise) {
    _categoriesPromise = (async () => {
      const fw = await loadFramework(BASE);
      const cats = [];
      for (const ring of fw.rings || []) {
        if (!CATEGORY_RINGS.includes(ring.id)) continue;
        for (const l of ring.letters || []) {
          cats.push({ id: l.id, ring: ring.name, letter: l.letter, name: l.name });
        }
      }
      cats.push({ id: 'other', ring: null, letter: '·', name: 'Other / Uncategorised' });
      return cats;
    })();
  }
  return _categoriesPromise;
}

// A frameworkRef "resolves to a chip" if its id equals one of the category ids
// (code.* / coder.*). The "other" category matches a post whose frameworkRef is
// missing OR does not match any chip id.
function categoryIdOf(post, chipIds) {
  const ref = post.frameworkRef;
  if (ref && chipIds.has(ref)) return ref;
  return 'other';
}

// ── visibility ───────────────────────────────────────────────────────────────
// Include published + flagged (flagged posts are NOT removed this pass — Step 6
// gives them a marked-for-deletion treatment). Exclude pending-review/draft/removed.
function isVisible(post) {
  return post.status === 'published' || post.status === 'flagged';
}

// ── engagement score (sort tiebreak) ─────────────────────────────────────────
function engagementScore(post) {
  const e = post.engagement || {};
  return (e.upvotes || 0) + 1.5 * (e.comments || 0) + 2 * (e.saves || 0);
}

// ── the read path ────────────────────────────────────────────────────────────
// filter = { categories?, tags?, since?, includeFlagged? } — all optional.
// The three filter dimensions (category, tags, since) compose with AND; within a
// dimension it is OR (any selected category, any selected tag).
export async function listPosts(filter = {}) {
  const { categories, tags, since, includeFlagged = true } = filter || {};
  const seed = await loadSeed();
  const flags = readFlags();
  const userPosts = readUserPosts();

  // category chip ids, to decide chip-vs-other and to honour the category filter
  const cats = await buildCategories();
  const chipIds = new Set(cats.map((c) => c.id).filter((id) => id !== 'other'));

  const wantCats = (categories && categories.length) ? new Set(categories) : null;
  const wantTags = (tags && tags.length) ? tags : null;
  const sinceMs = since ? new Date(since).getTime() : null;

  const out = [];
  for (const raw of [...seed, ...userPosts]) {
    const post = applyOverlay(raw, flags);

    // visibility
    if (!isVisible(post)) continue;
    if (post.status === 'flagged' && !includeFlagged) continue;

    // category dimension (OR within)
    if (wantCats) {
      if (!wantCats.has(categoryIdOf(post, chipIds))) continue;
    }
    // tags dimension (OR within)
    if (wantTags) {
      const topics = post.topics || [];
      if (!wantTags.some((t) => topics.includes(t))) continue;
    }
    // since dimension
    if (sinceMs != null) {
      const created = new Date(post.createdAt).getTime();
      if (!(created >= sinceMs)) continue;
    }

    out.push(post);
  }

  // SORT: recency DESC → engagement DESC → id ASC (total, deterministic order).
  out.sort((a, b) => {
    const ta = new Date(a.createdAt).getTime();
    const tb = new Date(b.createdAt).getTime();
    if (tb !== ta) return tb - ta;
    const ea = engagementScore(a);
    const eb = engagementScore(b);
    if (eb !== ea) return eb - ea;
    return String(a.id).localeCompare(String(b.id));
  });

  return out;
}

// Fetch one post by id across seed + userPosts, with the flags overlay applied.
// Returns null if not found. Does not filter by visibility — callers decide.
export async function getPost(id) {
  const seed = await loadSeed();
  const userPosts = readUserPosts();
  const flags = readFlags();
  const found = [...seed, ...userPosts].find((p) => p.id === id);
  return found ? applyOverlay(found, flags) : null;
}

// ── writes — seams for later steps (storage mechanics now; gating/validation later)
// createPost: Step 5 validates `item` against feed.schema.json BEFORE calling this.
// For now: assign nothing, just push to feedStore.userPosts and return the item.
export async function createPost(item) {
  // Step 5: the data layer is the real gate. Validate against feed.schema.json (+ the
  // ≤100-word post rule) BEFORE appending. The composer's inline errors are a UX nicety
  // on top of this — even a caller that skipped them cannot persist an invalid item.
  const v = await validateFeedItem(item);
  if (!v.ok) throw new Error('Invalid feed item: ' + v.errors.map((e) => e.message).join('; '));
  const userPosts = readUserPosts();
  userPosts.push(item);
  lsSet(K_USER_POSTS, userPosts);
  return item;
}

// flagPost: Step 6 builds the UI that calls this; the mechanics live here now.
// Reads the current flagCount (overlay → seed moderation.flagCount → 0), adds 1,
// and at/above FLAG_THRESHOLD flips status to 'flagged' (else keeps 'published').
export function flagPost(id) {
  const flags = readFlags();
  let baseCount = 0;
  if (flags[id] && typeof flags[id].flagCount === 'number') {
    baseCount = flags[id].flagCount;
  } else if (_seedSync) {
    // fall back to the seed's own moderation.flagCount (the seed is normally already
    // resolved by the time any flag UI exists; default to 0 if it isn't).
    const seedPost = _seedSync.find((p) => p.id === id);
    baseCount = (seedPost && seedPost.moderation && seedPost.moderation.flagCount) || 0;
  } else {
    baseCount = 0;
  }
  const flagCount = baseCount + 1;
  const status = flagCount >= FLAG_THRESHOLD ? 'flagged' : 'published';
  flags[id] = { flagCount, status };
  lsSet(K_FLAGS, flags);
  return { flagCount, status };
}

// ── filter-source helpers ────────────────────────────────────────────────────
// Sorted union of topics[] across VISIBLE posts (so the tag chips only ever offer
// tags that can actually return a result).
export async function getAllTopics() {
  const posts = await listPosts();
  const set = new Set();
  for (const p of posts) for (const t of (p.topics || [])) set.add(t);
  return [...set].sort();
}

// Category[] built from framework.json (see buildCategories above).
export async function getAllCategories() {
  return buildCategories();
}
