// TECHFLIX mode — browse-and-watch video episodes, grouped by topic.
//
// Consumes the read-only library endpoint:
//   GET /api/media/techflix -> { topics: [ { topic, episodes: [ {id, title,
//                                description, duration_sec, video_url,
//                                poster_url} ] } ] }
//
// Access is "any signed-in user": the API returns 401 when unauthenticated, and
// this view turns that into a friendly sign-in prompt rather than an error. The
// video bytes stream (with HTTP Range / scrubbing) from `video_url`
// (/media/video/{id}); that byte endpoint is unauthenticated, like all media.
//
// Layout is Netflix-style: one horizontal strip per topic, each a row of
// episode cards. Clicking a card opens a modal player. All design tokens come
// from monolith.css, so brand + dark mode carry over with no extra work.
//
// Every interpolated field is escaped (esc) — these are DATA values from the DB,
// never authored HTML.

import { esc } from '../../shared/dom.js';
import { API_BASE } from '../../core/config.js';
import { apiFetch } from '../../core/api.js';

const TECHFLIX_URL = '/api/media/techflix';

// Whole-second duration -> "M:SS" (e.g. 425 -> "7:05"). Empty when unknown
// (FFprobe was unavailable at upload time).
function fmtDuration(sec) {
  if (!sec || sec <= 0) return '';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function posterMarkup(ep) {
  if (ep.poster_url) {
    return `<img class="tfx-poster" src="${esc(API_BASE + ep.poster_url)}" alt="" loading="lazy">`;
  }
  // No poster yet — a branded placeholder seeded with the title.
  return `<span class="tfx-poster tfx-poster--ph" aria-hidden="true"><span>${esc(ep.title)}</span></span>`;
}

function cardMarkup(ep) {
  const dur = fmtDuration(ep.duration_sec);
  const badge = dur ? `<span class="tfx-badge">${esc(dur)}</span>` : '';
  const desc = ep.description ? `<span class="tfx-card-desc">${esc(ep.description)}</span>` : '';
  return `
    <button class="tfx-card" type="button"
            data-video="${esc(API_BASE + ep.video_url)}"
            data-title="${esc(ep.title)}"
            data-desc="${esc(ep.description || '')}">
      <span class="tfx-thumb">
        ${posterMarkup(ep)}
        <span class="tfx-play" aria-hidden="true">▶</span>
        ${badge}
      </span>
      <span class="tfx-card-body">
        <span class="tfx-card-title">${esc(ep.title)}</span>
        ${desc}
      </span>
    </button>`;
}

function rowMarkup(topic) {
  return `
    <section class="tfx-row">
      <h2 class="tfx-topic">${esc(topic.topic)}</h2>
      <div class="tfx-strip">${(topic.episodes || []).map(cardMarkup).join('')}</div>
    </section>`;
}

// Modal player. Appended to <body> so it overlays full-screen regardless of the
// view container. ESC / click-outside / close-button all dismiss; focus returns
// to the card that opened it.
function openPlayer({ video, title, desc }) {
  const opener = document.activeElement;
  const overlay = document.createElement('div');
  overlay.className = 'tfx-modal';
  overlay.innerHTML = `
    <div class="tfx-modal-box" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <button class="tfx-close" type="button" aria-label="Close player">✕</button>
      <video class="tfx-video" controls autoplay playsinline src="${esc(video)}"></video>
      <div class="tfx-modal-meta">
        <h3>${esc(title)}</h3>
        ${desc ? `<p>${esc(desc)}</p>` : ''}
      </div>
    </div>`;

  function close() {
    const v = overlay.querySelector('video');
    if (v) v.pause();
    overlay.remove();
    document.removeEventListener('keydown', onKey);
    if (opener && typeof opener.focus === 'function') opener.focus();
  }
  function onKey(e) {
    if (e.key === 'Escape') close();
  }

  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  overlay.querySelector('.tfx-close').addEventListener('click', close);
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
  overlay.querySelector('.tfx-close').focus();
}

export async function renderTechflix(mount) {
  mount.innerHTML = '<div class="loading">Loading…</div>';

  let data;
  try {
    const res = await apiFetch(TECHFLIX_URL, {
      headers: { Accept: 'application/json' },
    });
    if (res.status === 401) {
      mount.innerHTML =
        '<div class="tfx-wrap"><div class="placeholder">' +
        '<h2>Sign in to watch</h2>' +
        '<p>Techflix is available to signed-in DEPT® users. ' +
        'Use sign-in (top right) to start watching.</p></div></div>';
      return;
    }
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    data = await res.json();
  } catch (e) {
    mount.innerHTML =
      '<div class="tfx-wrap"><div class="placeholder">' +
      `<h2>Couldn’t load Techflix</h2><p>${esc(e.message)}</p></div></div>`;
    return;
  }

  const topics = (data && data.topics) || [];
  const header =
    '<header class="tfx-head">' +
    '<h1 class="tfx-title">Techflix</h1>' +
    '<p class="tfx-sub">Short technical episodes — 5 to 10 minutes, by topic.</p>' +
    '</header>';

  if (!topics.length) {
    mount.innerHTML =
      `<div class="tfx-wrap">${header}<div class="placeholder">` +
      '<h2>No episodes yet</h2>' +
      '<p>Videos appear here once they’re uploaded to the library.</p></div></div>';
    return;
  }

  mount.innerHTML = `<div class="tfx-wrap">${header}${topics.map(rowMarkup).join('')}</div>`;

  mount.querySelectorAll('.tfx-card').forEach((btn) => {
    btn.addEventListener('click', () => openPlayer({
      video: btn.dataset.video,
      title: btn.dataset.title,
      desc: btn.dataset.desc,
    }));
  });
}
