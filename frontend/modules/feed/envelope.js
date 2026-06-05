// The shared UGC envelope — pill, kind tag, author, topics, engagement, the
// frameworkRef bridge. Read by EVERY feed type so the card chrome is identical
// regardless of payload. All fields are user-supplied → escaped.
import { esc } from '../../shared/dom.js';

export function relativeTime(iso) {
  try {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'just now';
    const m = s / 60; if (m < 60) return Math.floor(m) + 'm';
    const h = m / 60; if (h < 24) return Math.floor(h) + 'h';
    const d = h / 24; if (d < 7) return Math.floor(d) + 'd';
    const w = d / 7; if (w < 5) return Math.floor(w) + 'w';
    const mo = d / 30; if (mo < 12) return Math.floor(mo) + 'mo';
    return Math.floor(d / 365) + 'y';
  } catch (e) { return ''; }
}

// ── frameworkRef → ring + letter ──────────────────────────────────────────────
// The bridge model. A ref looks like "coder.d" → ring "coder", letter "D".
// "code.*" → CODE ring (ochre pill); "coder.*" → CODER ring (blue pill). Anything
// else (missing, or a ring we don't pill, e.g. adobe.*) → null → a muted pill.
export function resolveRef(ref) {
  if (typeof ref !== 'string' || !ref.includes('.')) return null;
  const [ring, rest] = ref.split('.');
  if (ring !== 'code' && ring !== 'coder') return null;
  if (!rest) return null;
  // letter is the last dotted segment, uppercased (coder.d → "D", adobe.cja → "CJA")
  const letter = rest.split('.').pop().toUpperCase();
  return { ring, letter };
}

// The CODE/CODER pill in the card top. Derived from frameworkRef only. No/unresolved
// ref → a tasteful muted neutral pill carrying the kind so the slot is never empty
// of meaning. (The kind tag still names the type on the right.)
export function pill(item) {
  const r = resolveRef(item.frameworkRef);
  if (!r) return `<span class="pill muted">UGC</span>`;
  return `<span class="pill ${r.ring}">${esc(r.letter)}</span>`;
}

// The mono "kind" tag, right-aligned in the card top.
const KIND_LABEL = {
  post: 'Field Note · 100 words',
  video: 'Video',
  list: 'List',
  card: 'Concept',
  vocab: 'Vocab',
  scenario: 'Scenario'
};
export function kindTag(item) {
  return `<span class="kind">${esc(KIND_LABEL[item.type] || item.type)}</span>`;
}

// card-top = pill + kind. Shared by every type.
export function cardTop(item) {
  return `<div class="card-top">${pill(item)}${kindTag(item)}</div>`;
}

// Author block (avatar gradient + name + role) — used by the field-note (post).
export function authorBlock(item) {
  const a = item.author || {};
  const initials = (a.initials || (a.name || '?').slice(0, 2)).toUpperCase();
  const verified = a.verified
    ? ` <span class="verified" role="img" aria-label="Verified">✓</span>` : '';
  return `<div class="author">` +
    `<div class="avatar" aria-hidden="true">${esc(initials)}</div>` +
    `<div class="who"><div class="name">${esc(a.name || 'Unknown')}${verified}</div>` +
    `<div class="role">${esc(a.role || '')}</div></div></div>`;
}

// Topic chips (#tag) — clickable, set the tag filter (handler in feed.js).
export function topicChips(item) {
  const topics = (item.topics || []).map(
    (t) => `<button class="fc-topic" type="button" data-topic="${esc(t)}">#${esc(t)}</button>`
  ).join('');
  return topics ? `<div class="fc-topics">${topics}</div>` : '';
}

// The flagged BADGE at the top of a card — rendered (by feed.js's cardHTML) only when
// status === 'flagged'. The TEXT carries the moderation state ("Marked for deletion ·
// Pending review"), so the cue never rests on colour/opacity alone — a screen reader
// (and a greyscale display) still reads the meaning. The post body stays visible: this
// is "pending review", not removed; real deletion is a later moderator + backend action.
export function flaggedBadge(item) {
  if (!item || item.status !== 'flagged') return '';
  return `<div class="flag-badge" role="status">` +
    `<span class="flag-badge-glyph" aria-hidden="true">⚑</span>` +
    `Marked for deletion · Pending review</div>`;
}

// The shared card foot: engagement on the left, an ochre "Read {LETTER} →" bridge
// on the right when frameworkRef resolves to a framework address. The bridge links
// to #/read/<ref>; Read mode opens that chapter (the Feed→Course bridge).
// NOTE: not every chapter is extracted yet, so some bridge links land on Read's
// graceful "couldn't load" — acceptable this pass.
//
// FLAG CONTROL (Step 6) lives here, on the right of the foot, gated by `signedIn`:
//   • already flagged → a non-interactive "Flagged · Pending" indicator, so the same
//     browser cannot re-flag and keep inflating moderation.flagCount;
//   • signed in & not flagged → a real <button data-flag> that OPENS an inline confirm
//     (the confirm row is built by feed.js on click — not here, and never window.confirm);
//   • signed out → no flag control at all (browsing stays open; flagging needs a session).
export function renderFooter(item, signedIn) {
  const e = item.engagement || {};
  const engage = `<div class="engage" aria-label="Engagement">` +
    `<span title="Upvotes">▲ ${esc(e.upvotes || 0)}</span>` +
    `<span title="Comments">❝ ${esc(e.comments || 0)}</span>` +
    `<span title="Saves">⤓ ${esc(e.saves || 0)}</span></div>`;
  const r = resolveRef(item.frameworkRef);
  const go = r
    ? `<a class="go" href="#/read/${esc(item.frameworkRef)}">Read ${esc(r.letter)} →</a>` : '';
  return `<footer class="card-foot">${engage}${go}${flagControl(item, signedIn)}</footer>`;
}

// The flag affordance for one card. Returns '' when signed out (no control at all).
function flagControl(item, signedIn) {
  if (!signedIn) return '';
  if (item.status === 'flagged') {
    // Replaced control: a plain indicator, NOT a button — this browser already flagged
    // it, so it must not be able to re-flag. The text reads the state.
    return `<span class="flagged-indicator">⚑ Flagged · Pending</span>`;
  }
  return `<button class="flag-btn" type="button" data-flag="${esc(item.id)}" ` +
    `aria-label="Flag this post for review">⚑ Flag</button>`;
}

// The inline, accessible confirm row injected into a card foot when its Flag button is
// pressed (built here so the markup stays with the rest of the foot chrome; feed.js owns
// the open/close + focus management). Two real <button>s; ESC / Cancel dismiss it.
export function flagConfirmHTML(id) {
  return `<div class="flag-confirm" role="group" aria-label="Confirm flag this post for review">` +
    `<span class="flag-confirm-q">Flag this post for review?</span>` +
    `<span class="flag-confirm-acts">` +
    `<button class="flag-confirm-yes" type="button" data-flag-confirm="${esc(id)}">Confirm</button>` +
    `<button class="flag-confirm-no" type="button" data-flag-cancel="${esc(id)}">Cancel</button>` +
    `</span></div>`;
}
