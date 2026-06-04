// The shared UGC envelope — author, time, topics, engagement, the frameworkRef bridge.
// Read by EVERY feed type so the card chrome is identical regardless of payload.
// All fields are user-supplied → escaped.
import { esc } from '../util/dom.js';

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

export function renderAuthor(item) {
  const a = item.author || {};
  const initials = (a.initials || (a.name || '?').slice(0, 2)).toUpperCase();
  const verified = a.verified ? ' <span class="fc-verified" role="img" title="Verified" aria-label="Verified">✓</span>' : '';
  return `<header class="fc-head">` +
    `<div class="fc-avatar" aria-hidden="true">${esc(initials)}</div>` +
    `<div class="fc-author"><div class="fc-name">${esc(a.name || 'Unknown')}${verified}</div>` +
    `<div class="fc-role">${esc(a.role || '')}</div></div>` +
    `<div class="fc-time">${esc(relativeTime(item.createdAt))}</div>` +
    `</header>`;
}

export function renderFooter(item) {
  const topics = (item.topics || []).map(
    (t) => `<button class="fc-topic" type="button" data-topic="${esc(t)}">#${esc(t)}</button>`
  ).join('');
  const e = item.engagement || {};
  const engage = `<div class="fc-engage" aria-label="engagement">` +
    `<span title="Upvotes">▲ ${esc(e.upvotes || 0)}</span>` +
    `<span title="Comments">❝ ${esc(e.comments || 0)}</span>` +
    `<span title="Saves">⤓ ${esc(e.saves || 0)}</span></div>`;
  const ref = item.frameworkRef
    ? `<a class="fc-ref" href="#/read/${esc(item.frameworkRef)}">Read the chapter →</a>` : '';
  return `<footer class="fc-foot"><div class="fc-topics">${topics}</div>${engage}${ref}</footer>`;
}
