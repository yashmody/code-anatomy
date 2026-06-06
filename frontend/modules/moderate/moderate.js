// MODERATE mode — the moderator review surface (Phase 4b, slice C).
//
// Consumes the live moderation backend:
//   GET  /api/moderate/queue   -> { feed_items: [...], questions: [...] }
//   POST /api/moderate/action  <- { item_id, item_type:"feed"|"question",
//                                   action:"approve"|"flag"|"remove" }
//
// The route is role-gated in core/main.js (hasPermission('moderate.view')); the
// API ALSO enforces moderate.view / moderate.action server-side, so this view
// never grants access it shouldn't — a 403 here means the session lost the role
// since boot, and we say so plainly.
//
// FEED items reuse the Feed's own card composition (renderFeedBody + envelope
// chrome + media) so a flagged post looks exactly like it does in the stream,
// with a moderation toolbar bolted on. QUESTIONS render as compact review cards
// (prompt + options with the correct answer marked + author + status) — they are
// quiz-bank rows, not feed cards, so they get their own shape.
//
// State lives in this module's closure for one mount. Each successful action
// mutates the in-memory lists and repaints, so the queue shrinks as you work it
// without a full re-fetch. Focus is restored after every repaint (a11y).

import { renderFeedBody } from '../../shared/registry.js';
import { flaggedBadge, topicChips } from '../feed/envelope.js';
import { renderDiagram, runMermaid } from '../../shared/render/diagram.js';
import { esc } from '../../shared/dom.js';

// Media renderer — inlined (NOT imported from ../feed/media.js).
// media.js currently has a broken relative import ('../render/diagram.js' →
// no such path; the file lives at ../../shared/render/diagram.js), so importing
// it would make THIS module fail to load. Until that pre-existing feed bug is
// fixed, we render media here using the correct renderDiagram import. Mirrors
// media.js's behaviour: image → <figure><img>, diagram → renderDiagram. Same
// alt/caption discipline; all fields escaped.
function renderModMedia(media) {
  if (!media || !media.length) return '';
  return media.map((m) => {
    if (m.kind === 'image') {
      if (!m.url) return '';
      const alt = esc(m.alt || '');
      const dims = (m.width && m.height) ? ` width="${esc(m.width)}" height="${esc(m.height)}"` : '';
      const cap = m.caption ? `<figcaption class="fc-cap">${esc(m.caption)}</figcaption>` : '';
      return `<figure class="fc-media fc-media-img"><img src="${esc(m.url)}" alt="${alt}" loading="lazy"${dims}>${cap}</figure>`;
    }
    if (m.kind === 'diagram') {
      return `<div class="fc-media fc-media-diagram">${renderDiagram({ render: m.render, source: m.source, url: m.url, alt: m.alt })}</div>`;
    }
    return '';
  }).join('');
}

const QUEUE_URL = '/api/moderate/queue';
const ACTION_URL = '/api/moderate/action';

// The three moderator verbs. Kept as data so the toolbar, the POST, and the
// optimistic local update all agree on the same set.
const ACTIONS = [
  { action: 'approve', label: 'Approve', cls: 'mod-act-approve' },
  { action: 'flag', label: 'Flag', cls: 'mod-act-flag' },
  { action: 'remove', label: 'Remove', cls: 'mod-act-remove', destructive: true }
];

export async function renderModerate(mount) {
  // ── per-mount state ───────────────────────────────────────────────────────
  let feedItems = [];
  let questions = [];
  // A selector for the control to refocus after the next repaint (a11y). Set by
  // a handler just before it triggers a repaint; consumed once.
  let nextFocus = null;
  // The id of the item whose Remove confirm is currently open (only one at a time).
  let confirmOpen = null;

  mount.innerHTML = '<div class="loading">Loading moderation queue…</div>';

  try {
    const res = await fetch(QUEUE_URL, { headers: { Accept: 'application/json' } });
    if (res.status === 403 || res.status === 401) {
      renderForbidden(mount);
      return;
    }
    if (!res.ok) throw new Error(`Queue request failed (${res.status})`);
    const data = await res.json();
    feedItems = Array.isArray(data.feed_items) ? data.feed_items : [];
    questions = Array.isArray(data.questions) ? data.questions : [];
  } catch (e) {
    renderError(mount, e);
    return;
  }

  // ── one moderation toolbar (shared by feed cards + question cards) ─────────
  function toolbar(id, type) {
    const confirming = confirmOpen === id;
    const btns = ACTIONS.map((a) => {
      if (a.destructive) {
        // Remove opens an inline accessible confirm instead of acting immediately.
        return `<button class="mod-act ${a.cls}" type="button" ` +
          `data-confirm-remove="${esc(id)}" data-type="${esc(type)}" ` +
          `aria-expanded="${confirming}">${a.label}</button>`;
      }
      return `<button class="mod-act ${a.cls}" type="button" ` +
        `data-action="${a.action}" data-id="${esc(id)}" data-type="${esc(type)}">${a.label}</button>`;
    }).join('');
    const confirm = confirming ? removeConfirmHTML(id, type) : '';
    return `<div class="mod-toolbar" role="group" aria-label="Moderation actions">${btns}${confirm}</div>`;
  }

  // The inline, accessible Remove-confirm — modelled on the Feed's flag-confirm
  // pattern (envelope.flagConfirmHTML): two real <button>s, ESC / Cancel dismiss.
  function removeConfirmHTML(id, type) {
    return `<div class="mod-confirm" role="group" aria-label="Confirm remove this item">` +
      `<span class="mod-confirm-q">Remove this ${esc(type === 'question' ? 'question' : 'post')}? It leaves the queue.</span>` +
      `<span class="mod-confirm-acts">` +
      `<button class="mod-confirm-yes" type="button" data-do-remove="${esc(id)}" data-type="${esc(type)}">Remove</button>` +
      `<button class="mod-confirm-no" type="button" data-cancel-remove="${esc(id)}">Cancel</button>` +
      `</span></div>`;
  }

  // ── FEED card — reuse the stream's body + chrome, append the toolbar ───────
  function feedCardHTML(it) {
    const flagged = it.status === 'flagged' ? ' card--flagged' : '';
    return `<article class="card mod-card${flagged}" data-mod-id="${esc(it.id)}" ` +
      `data-mod-type="feed" tabindex="-1">` +
      `<div class="mod-status mod-status--${esc(it.status || 'pending')}">${esc(statusLabel(it.status))}</div>` +
      flaggedBadge(it) +
      renderFeedBody(it) +
      topicChips(it) +
      renderModMedia(it.media) +
      toolbar(it.id, 'feed') +
      `</article>`;
  }

  // ── QUESTION review card — compact: prompt, options (correct marked), meta ─
  function questionCardHTML(q) {
    const opts = Array.isArray(q.options) ? q.options : [];
    const correct = Number.isInteger(q.correct_index) ? q.correct_index : -1;
    const optsHTML = opts.map((o, i) => {
      const isCorrect = i === correct;
      const mark = isCorrect
        ? `<span class="mq-correct-tag" aria-label="Correct answer">✓ correct</span>` : '';
      return `<li class="mq-option${isCorrect ? ' mq-option--correct' : ''}">` +
        `<span class="mq-option-text">${esc(o)}</span>${mark}</li>`;
    }).join('');
    const explanation = q.explanation
      ? `<p class="mq-explain"><span class="mq-explain-tag">Reveal</span> ${esc(q.explanation)}</p>` : '';
    const ugc = q.is_user_submitted ? `<span class="mq-ugc">UGC</span>` : '';
    return `<article class="card mod-card mod-card--question" data-mod-id="${esc(q.id)}" ` +
      `data-mod-type="question" tabindex="-1">` +
      `<div class="mod-card-top">` +
        `<span class="mq-kind">Question · ${esc(q.topic || 'general')} · ${esc(q.difficulty || '—')}</span>` +
        `<span class="mod-status mod-status--${esc(q.status || 'pending')}">${esc(statusLabel(q.status))}</span>` +
      `</div>` +
      `<div class="card-body">` +
        `<h3 class="mq-prompt">${esc(q.question || 'Untitled question')}</h3>` +
        (optsHTML ? `<ul class="mq-options">${optsHTML}</ul>` : '') +
        explanation +
        `<div class="mq-meta">${ugc}<span class="mq-author">${esc(q.author_id || 'unknown')}</span></div>` +
      `</div>` +
      toolbar(q.id, 'question') +
      `</article>`;
  }

  // ── full paint ────────────────────────────────────────────────────────────
  function paint() {
    if (!feedItems.length && !questions.length) {
      mount.innerHTML =
        `<section class="mod-wrap"><div class="mod-head">` +
        `<h1 class="mod-title">Moderation</h1>` +
        `<p class="mod-sub">Pending and flagged content awaiting review.</p></div>` +
        `<div class="mod-empty" role="status">` +
        `<span class="mod-empty-glyph" aria-hidden="true">✓</span>` +
        `<p class="mod-empty-text">Queue is clear. Nothing is waiting for review.</p>` +
        `</div></section>`;
      return;
    }

    const feedSection = feedItems.length
      ? `<section class="mod-section" aria-labelledby="modFeedH">` +
          `<h2 class="mod-section-h" id="modFeedH">Feed items ` +
          `<span class="mod-count">${feedItems.length}</span></h2>` +
          `<div class="mod-list">${feedItems.map(feedCardHTML).join('')}</div>` +
        `</section>`
      : '';

    const qSection = questions.length
      ? `<section class="mod-section" aria-labelledby="modQH">` +
          `<h2 class="mod-section-h" id="modQH">Questions ` +
          `<span class="mod-count">${questions.length}</span></h2>` +
          `<div class="mod-list">${questions.map(questionCardHTML).join('')}</div>` +
        `</section>`
      : '';

    mount.innerHTML =
      `<section class="mod-wrap"><div class="mod-head">` +
      `<h1 class="mod-title">Moderation</h1>` +
      `<p class="mod-sub">Pending and flagged content awaiting review. ` +
      `Actions take effect immediately and remove the item from this queue.</p></div>` +
      `<div class="mod-toast" id="modToast" role="status" aria-live="polite" hidden></div>` +
      feedSection + qSection + `</section>`;

    // Diagrams in flagged feed cards (some feed bodies carry mermaid media).
    runMermaid(mount).catch(() => {});

    // Restore focus after the repaint (a11y) — to an explicit target if a
    // handler set one, else leave focus where the browser put it.
    if (nextFocus) {
      const el = mount.querySelector(nextFocus);
      if (el) el.focus();
      nextFocus = null;
    }
  }

  // ── toast (small confirmation) ────────────────────────────────────────────
  let toastTimer = null;
  function toast(msg, isError) {
    const el = mount.querySelector('#modToast');
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('mod-toast--error', !!isError);
    el.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
  }

  // ── the action call ───────────────────────────────────────────────────────
  async function doAction(id, type, action) {
    try {
      const res = await fetch(ACTION_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ item_id: id, item_type: type, action })
      });
      if (res.status === 403 || res.status === 401) {
        toast('Not authorised — your moderator session may have ended.', true);
        return;
      }
      if (!res.ok) throw new Error(`Action failed (${res.status})`);

      // Success: drop the item from its list and repaint. Every action
      // (approve / flag / remove) moves the row out of the pending/flagged
      // queue server-side, so it leaves this view either way.
      if (type === 'feed') feedItems = feedItems.filter((x) => x.id !== id);
      else questions = questions.filter((x) => x.id !== id);
      confirmOpen = null;
      paint();
      toast(`${capitalise(action)}d. Item left the queue.`);
    } catch (e) {
      toast(`Couldn’t ${action} this item. ${e.message}`, true);
    }
  }

  // ── one delegated click handler for the whole surface ─────────────────────
  mount.addEventListener('click', (e) => {
    const t = e.target.closest('button');
    if (!t) return;

    // Direct action (Approve / Flag).
    if (t.dataset.action) {
      doAction(t.dataset.id, t.dataset.type, t.dataset.action);
      return;
    }
    // Open the Remove confirm.
    if (t.dataset.confirmRemove != null) {
      confirmOpen = t.dataset.confirmRemove;
      nextFocus = `[data-do-remove="${cssEsc(confirmOpen)}"]`;
      paint();
      return;
    }
    // Confirm the Remove.
    if (t.dataset.doRemove != null) {
      doAction(t.dataset.doRemove, t.dataset.type, 'remove');
      return;
    }
    // Cancel the Remove — return focus to the card's Remove button.
    if (t.dataset.cancelRemove != null) {
      const id = t.dataset.cancelRemove;
      confirmOpen = null;
      nextFocus = `[data-confirm-remove="${cssEsc(id)}"]`;
      paint();
      return;
    }
  });

  // ESC closes an open Remove confirm.
  mount.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && confirmOpen) {
      const id = confirmOpen;
      confirmOpen = null;
      nextFocus = `[data-confirm-remove="${cssEsc(id)}"]`;
      paint();
    }
  });

  paint();
}

// ── module-level helpers ──────────────────────────────────────────────────────
function statusLabel(status) {
  const map = {
    pending_review: 'Pending review',
    'pending-review': 'Pending review',
    flagged: 'Flagged',
    draft: 'Draft',
    published: 'Published',
    removed: 'Removed',
    archived: 'Archived'
  };
  return map[status] || (status ? String(status) : 'Pending');
}

function capitalise(s) {
  return String(s || '').charAt(0).toUpperCase() + String(s || '').slice(1);
}

// CSS.escape with a defensive fallback (older engines / tests).
function cssEsc(s) {
  if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(String(s));
  return String(s).replace(/["\\]/g, '\\$&');
}

function renderForbidden(mount) {
  mount.innerHTML =
    `<div class="placeholder"><h2>Not authorised</h2>` +
    `<p>Moderation is restricted to moderators. Sign in with a moderator ` +
    `account to review the queue.</p></div>`;
}

function renderError(mount, e) {
  mount.innerHTML =
    `<div class="placeholder"><h2>Couldn’t load the queue</h2>` +
    `<p>${esc(e && e.message ? e.message : 'Network error.')} Try again shortly.</p></div>`;
}
