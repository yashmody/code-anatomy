// WHAT'S NEW mode — latest Adobe updates, refreshed weekly by the content-refresh
// sync. Read-only for any signed-in user.
//
//   GET /api/whatsnew -> { items:[...], groups:[ {product, items:[ {id, title,
//                          summary, source_url, published_at, related_chapter} ]} ] }
//
// The endpoint requires auth (401 when signed out → friendly prompt here). Items
// link out to their Adobe source (new tab). Every field is escaped — these are
// DB values, never authored HTML.

import { esc } from '../../shared/dom.js';
import { apiFetch } from '../../core/api.js';

const WHATSNEW_URL = '/api/whatsnew';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

function itemMarkup(it) {
  const date = fmtDate(it.published_at);
  const dateBadge = date ? `<span class="wn-date">${esc(date)}</span>` : '';
  const summary = it.summary ? `<p class="wn-summary">${esc(it.summary)}</p>` : '';
  // Source link only when on the trusted Adobe host (defensive; data is ours).
  const safe = typeof it.source_url === 'string' && it.source_url.startsWith('https://experienceleague.adobe.com/');
  const link = safe
    ? `<a class="wn-src" href="${esc(it.source_url)}" target="_blank" rel="noopener noreferrer">Source ↗</a>`
    : '';
  return `
    <article class="wn-item">
      <div class="wn-item-head">
        <h3 class="wn-title">${esc(it.title)}</h3>
        ${dateBadge}
      </div>
      ${summary}
      ${link}
    </article>`;
}

function groupMarkup(group) {
  return `
    <section class="wn-group">
      <h2 class="wn-product">${esc(group.product)}</h2>
      <div class="wn-list">${(group.items || []).map(itemMarkup).join('')}</div>
    </section>`;
}

export async function renderWhatsNew(mount) {
  mount.innerHTML = '<div class="loading">Loading…</div>';

  let data;
  try {
    const res = await apiFetch(WHATSNEW_URL, {
      headers: { Accept: 'application/json' },
    });
    if (res.status === 401) {
      mount.innerHTML =
        '<div class="wn-wrap"><div class="placeholder">' +
        '<h2>Sign in to see What’s New</h2>' +
        '<p>The latest Adobe updates are available to signed-in DEPT® users. ' +
        'Use sign-in (top right).</p></div></div>';
      return;
    }
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    data = await res.json();
  } catch (e) {
    mount.innerHTML =
      '<div class="wn-wrap"><div class="placeholder">' +
      `<h2>Couldn’t load What’s New</h2><p>${esc(e.message)}</p></div></div>`;
    return;
  }

  const groups = (data && data.groups) || [];
  const header =
    '<header class="wn-head">' +
    '<h1 class="wn-h1">What’s New</h1>' +
    '<p class="wn-sub">Latest from the Adobe Experience Cloud — refreshed weekly.</p>' +
    '</header>';

  if (!groups.length) {
    mount.innerHTML =
      `<div class="wn-wrap">${header}<div class="placeholder">` +
      '<h2>Nothing yet</h2><p>Updates appear here after the next weekly sync.</p>' +
      '</div></div>';
    return;
  }

  mount.innerHTML = `<div class="wn-wrap">${header}${groups.map(groupMarkup).join('')}</div>`;
}
