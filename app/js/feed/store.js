// feedStore — the feed data layer. THE SEAM.
// Upgraded to connect directly to the FastAPI PostgreSQL backend.

import { validateFeedItem } from './validate.js';

export const FLAG_THRESHOLD = 1;

let BASE = '../content-architecture';
export function configureFeedStore(base) {
  if (base) BASE = base;
}
export function getFeedBase() {
  return BASE;
}

// Session pass-throughs (session management is now handled inside auth.js via backend cookies)
export function getSession() {
  return null;
}
export function setSession(session) {
}
export function clearSession() {
}

// Module-level cache for framework categories
let _categoriesPromise = null;
const CATEGORY_RINGS = ['code', 'coder'];

async function buildCategories() {
  if (!_categoriesPromise) {
    _categoriesPromise = (async () => {
      const res = await fetch('/api/course/framework');
      if (!res.ok) throw new Error('Failed to fetch framework from server');
      const fw = await res.json();
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

function categoryIdOf(post, chipIds) {
  const ref = post.frameworkRef;
  if (ref && chipIds.has(ref)) return ref;
  return 'other';
}

function engagementScore(post) {
  const e = post.engagement || {};
  return (e.upvotes || 0) + 1.5 * (e.comments || 0) + 2 * (e.saves || 0);
}

export async function listPosts(filter = {}) {
  const { categories, tags, since, includeFlagged = true } = filter || {};
  
  const res = await fetch('/api/feed');
  if (!res.ok) throw new Error('Failed to fetch feed from server');
  const data = await res.json();
  const allPosts = data.feed || [];

  const cats = await buildCategories();
  const chipIds = new Set(cats.map((c) => c.id).filter((id) => id !== 'other'));

  const wantCats = (categories && categories.length) ? new Set(categories) : null;
  const wantTags = (tags && tags.length) ? tags : null;
  const sinceMs = since ? new Date(since).getTime() : null;

  const out = [];
  for (const post of allPosts) {
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

export async function getPost(id) {
  const res = await fetch('/api/feed');
  if (!res.ok) return null;
  const data = await res.json();
  const allPosts = data.feed || [];
  return allPosts.find((p) => p.id === id) || null;
}

export async function createPost(item) {
  const v = await validateFeedItem(item);
  if (!v.ok) throw new Error('Invalid feed item: ' + v.errors.map((e) => e.message).join('; '));

  const res = await fetch('/api/feed', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(item)
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || 'Failed to save post on server.');
  }

  return item;
}

export async function flagPost(id) {
  const res = await fetch('/api/feed/flag', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ item_id: id })
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || 'Failed to flag post on server.');
  }

  return await res.json();
}

export async function getAllTopics() {
  const posts = await listPosts();
  const set = new Set();
  for (const p of posts) for (const t of (p.topics || [])) set.add(t);
  return [...set].sort();
}

export async function getAllCategories() {
  return buildCategories();
}
