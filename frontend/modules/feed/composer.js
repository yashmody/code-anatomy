// feed/composer.js — THE composer. One modal that creates ANY of the six feed types
// and appends a schema-valid item to the client-side feed via the store seam.
//
// Gated behind a signed-in @deptagency.com session (Step 4): the trigger only shows
// when signed in, and submit calls requireSession() before it does anything.
//
// What it does NOT do: touch localStorage (that is store.js only), edit the schema, or
// own ordering (a brand-new createdAt sorts to the top via the store's recency sort).
//
// Shape of the work:
//   • a type picker (radio strip) swaps the per-type fields; the envelope fields hold steady
//   • envelope: category (ring→letter→frameworkRef, or "Other" → no ref), tag chips → topics[]
//   • per-type payload fields, with the live ≤100-word counter on `post`
//   • optional single media item (URL only this pass) with a tiny live preview
//   • build → requireSession → validateFeedItem → createPost → close → repaint → toast
//
// Accessibility: role="dialog" aria-modal, labelled by its heading, focus trap, ESC +
// backdrop close, focus returns to the trigger, every input labelled, errors via
// aria-describedby + an aria-live summary, the word counter is aria-live polite.

import { esc } from '../util/dom.js';
import { requireSession } from './auth.js';
import { getAllCategories, createPost } from './store.js';
import { validateFeedItem } from './validate.js';
import { renderDiagram, runMermaid } from '../render/diagram.js';

const TYPES = [
  { id: 'post', label: 'Post' },
  { id: 'video', label: 'Video' },
  { id: 'list', label: 'List' },
  { id: 'card', label: 'Card' },
  { id: 'vocab', label: 'Vocab' },
  { id: 'scenario', label: 'Scenario' }
];

const WORD_CAP = 100;
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// A client id matching ^post\.[a-z0-9]+$ — 'post.' + 8 lowercase-alnum chars. This is a
// client id (not an ordering key), so randomness is fine; we only need the pattern.
function newId() {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let s = '';
  for (let i = 0; i < 8; i++) s += alphabet[Math.floor(Math.random() * alphabet.length)];
  return 'post.' + s;
}

// Count words the same way the validator/validate.py does (whitespace split, drop empties).
function wordCount(str) {
  return String(str || '').split(/\s+/).filter(Boolean).length;
}

// ── the controller ───────────────────────────────────────────────────────────────
// openComposer({ onPosted, returnFocusTo }) builds the modal, mounts it, traps focus,
// and resolves nothing — it cleans itself up on close. onPosted() fires after a
// successful createPost so the host (feed.js) can repaint. returnFocusTo is the trigger
// element focus returns to on close.
export async function openComposer({ onPosted, returnFocusTo } = {}) {
  // Gate up front. If somehow signed out, do not even build the modal.
  let session;
  try { session = requireSession(); }
  catch (e) { if (onPosted) { /* host handles its own toast */ } throw e; }

  const categories = await getAllCategories(); // [{id, ring, letter, name}], includes 'other'

  // ── editor state (the closure is the single source of truth) ──
  const state = {
    type: 'post',
    categoryId: 'other',     // 'other' → no frameworkRef
    tags: [],                // topics[]
    // per-type field bags (only the active type's bag is read at submit)
    listRows: [{ text: '', note: '' }],
    scnOptions: ['', ''],
    scnCorrect: 0,
    media: null              // null | {kind:'image',url,alt} | {kind:'diagram',render,source?,url?,alt}
  };

  // ── build the DOM ──
  const backdrop = document.createElement('div');
  backdrop.className = 'composer-backdrop';
  backdrop.innerHTML = shellHTML(categories);
  document.body.appendChild(backdrop);
  document.body.classList.add('composer-open');

  const dialog = backdrop.querySelector('.composer');
  const fieldsHost = backdrop.querySelector('[data-fields]');
  const summary = backdrop.querySelector('.composer-summary');

  // The simple (non-array) text/number fields whose values must SURVIVE a re-paint.
  // Adding/removing a list row or scenario option re-renders fieldsHost, which would
  // otherwise wipe whatever was already typed into these. We snapshot them before the
  // re-render and restore after. (Array-shaped fields — list rows, scenario options —
  // already live in state and are re-rendered from there.)
  const SCALAR_NAMES = ['title', 'intro', 'body', 'hook', 'url', 'durationSec',
    'teaser', 'linkUrl', 'term', 'definition', 'prompt', 'verdict', 'reveal'];

  function snapshotScalars() {
    const snap = {};
    for (const name of SCALAR_NAMES) {
      const el = fieldsHost.querySelector(`[name="${name}"]`);
      if (el) snap[name] = el.value;
    }
    return snap;
  }
  function restoreScalars(snap) {
    if (!snap) return;
    for (const name of SCALAR_NAMES) {
      const el = fieldsHost.querySelector(`[name="${name}"]`);
      if (el && snap[name] != null) el.value = snap[name];
    }
  }

  // paint the type-specific fields for the current type. `preserve` (a scalar snapshot)
  // is restored after the re-render — passed when re-painting due to a row add/remove so
  // typed values in the other fields are not lost.
  function paintFields(preserve) {
    fieldsHost.innerHTML = typeFieldsHTML(state, categories);
    wireDynamic();
    restoreScalars(preserve);
    restoreMedia();
    // the post counter starts fresh each time post is the active type
    if (state.type === 'post') updateCounter();
  }

  // Re-apply an in-progress media item to the freshly-rendered media controls so a row
  // add/remove (which re-paints fieldsHost) doesn't drop it. Opens the <details>, selects
  // the kind, renders its sub-fields, and refills the values from state.media.
  function restoreMedia() {
    const m = state.media;
    if (!m) return;
    const det = fieldsHost.querySelector('.composer-media');
    const kindSel = fieldsHost.querySelector('[name="media-kind"]');
    if (!det || !kindSel) return;
    det.open = true;
    kindSel.value = m.kind;
    _lastMediaKind = '';
    syncMediaSubFields(m.kind);
    const set = (name, val) => { const el = fieldsHost.querySelector(`[name="${name}"]`); if (el && val != null) el.value = val; };
    if (m.kind === 'image') { set('media-url', m.url); set('media-alt', m.alt); }
    else { set('media-render', m.render); set('media-source', m.source); set('media-url', m.url); set('media-alt', m.alt); }
    paintMediaPreview();
  }

  // ── per-type dynamic wiring (rows editors, options, media, counter) ──
  function wireDynamic() {
    // post word counter
    const body = fieldsHost.querySelector('[name="body"]');
    if (body) body.addEventListener('input', updateCounter);

    // list rows
    fieldsHost.querySelectorAll('[data-list-row]').forEach((row) => {
      const idx = Number(row.dataset.listRow);
      row.querySelector('[name="li-text"]').addEventListener('input', (e) => { state.listRows[idx].text = e.target.value; });
      const note = row.querySelector('[name="li-note"]');
      if (note) note.addEventListener('input', (e) => { state.listRows[idx].note = e.target.value; });
    });

    // scenario options
    fieldsHost.querySelectorAll('[data-scn-opt]').forEach((row) => {
      const idx = Number(row.dataset.scnOpt);
      row.querySelector('[name="scn-opt-text"]').addEventListener('input', (e) => { state.scnOptions[idx] = e.target.value; });
      const radio = row.querySelector('[name="scn-correct"]');
      if (radio) radio.addEventListener('change', () => { state.scnCorrect = idx; });
    });

    // media kind + fields
    const mediaKind = fieldsHost.querySelector('[name="media-kind"]');
    if (mediaKind) mediaKind.addEventListener('change', () => { rebuildMediaFromInputs(); paintMediaPreview(); });
    fieldsHost.querySelectorAll('[data-media-field]').forEach((inp) => {
      inp.addEventListener('input', () => { rebuildMediaFromInputs(); paintMediaPreview(); });
    });
  }

  function updateCounter() {
    const body = fieldsHost.querySelector('[name="body"]');
    const counter = fieldsHost.querySelector('.composer-counter');
    if (!body || !counter) return;
    const n = wordCount(body.value);
    counter.textContent = `${n} / ${WORD_CAP}`;
    counter.classList.toggle('over', n > WORD_CAP);
    counter.classList.toggle('near', n > WORD_CAP - 15 && n <= WORD_CAP);
  }

  // Read the media sub-form inputs into state.media (null if no kind chosen).
  function rebuildMediaFromInputs() {
    const kind = fieldsHost.querySelector('[name="media-kind"]');
    if (!kind || !kind.value) { state.media = null; return; }
    if (kind.value === 'image') {
      const url = (fieldsHost.querySelector('[name="media-url"]') || {}).value || '';
      const alt = (fieldsHost.querySelector('[name="media-alt"]') || {}).value || '';
      state.media = { kind: 'image', url: url.trim(), alt: alt.trim() };
    } else if (kind.value === 'diagram') {
      const render = (fieldsHost.querySelector('[name="media-render"]') || {}).value || 'mermaid';
      const alt = (fieldsHost.querySelector('[name="media-alt"]') || {}).value || '';
      const m = { kind: 'diagram', render, alt: alt.trim() };
      if (render === 'image') {
        m.url = ((fieldsHost.querySelector('[name="media-url"]') || {}).value || '').trim();
      } else {
        m.source = ((fieldsHost.querySelector('[name="media-source"]') || {}).value || '').trim();
      }
      state.media = m;
    } else {
      state.media = null;
    }
    // re-render the kind-specific sub-fields when kind changes (image vs diagram differ)
    syncMediaSubFields(kind.value);
  }

  // Swap the media sub-fields to match the chosen kind, preserving the alt text.
  let _lastMediaKind = '';
  function syncMediaSubFields(kind) {
    if (kind === _lastMediaKind) return;
    _lastMediaKind = kind;
    const host = fieldsHost.querySelector('[data-media-sub]');
    if (!host) return;
    host.innerHTML = mediaSubHTML(kind);
    host.querySelectorAll('[data-media-field]').forEach((inp) => {
      inp.addEventListener('input', () => { rebuildMediaFromInputs(); paintMediaPreview(); });
    });
    const render = host.querySelector('[name="media-render"]');
    if (render) render.addEventListener('change', () => { _lastMediaKind = ''; rebuildMediaFromInputs(); paintMediaPreview(); });
  }

  function paintMediaPreview() {
    const prev = fieldsHost.querySelector('.composer-media-preview');
    if (!prev) return;
    const m = state.media;
    if (!m) { prev.innerHTML = ''; return; }
    if (m.kind === 'image') {
      prev.innerHTML = m.url
        ? `<figure class="fc-media fc-media-img"><img src="${esc(m.url)}" alt="${esc(m.alt)}" loading="lazy"></figure>`
        : `<p class="composer-hint">Add an image URL to preview.</p>`;
      return;
    }
    // diagram
    if (m.render === 'image') {
      prev.innerHTML = m.url
        ? `<figure class="fc-media fc-media-img"><img src="${esc(m.url)}" alt="${esc(m.alt)}" loading="lazy"></figure>`
        : `<p class="composer-hint">Add an image URL to preview.</p>`;
      return;
    }
    if (!m.source) { prev.innerHTML = `<p class="composer-hint">Add diagram source to preview.</p>`; return; }
    prev.innerHTML = `<div class="fc-media fc-media-diagram">${renderDiagram({ render: m.render, source: m.source, alt: m.alt })}</div>`;
    if (m.render === 'mermaid') runMermaid(prev);
  }

  // ── envelope wiring (category, tags) — these elements live outside fieldsHost ──
  const catSelect = backdrop.querySelector('[name="category"]');
  catSelect.addEventListener('change', () => { state.categoryId = catSelect.value; });

  const tagInput = backdrop.querySelector('[name="tag-input"]');
  const tagChips = backdrop.querySelector('.composer-chips');
  function renderChips() {
    tagChips.innerHTML = state.tags.map((t, i) =>
      `<span class="composer-chip">#${esc(t)}<button type="button" class="composer-chip-x" data-chip="${i}" aria-label="Remove tag ${esc(t)}">×</button></span>`
    ).join('');
  }
  function addTagFromInput() {
    const raw = tagInput.value.trim().toLowerCase().replace(/^#/, '');
    if (raw && !state.tags.includes(raw)) state.tags.push(raw);
    tagInput.value = '';
    renderChips();
  }
  tagInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTagFromInput(); }
    else if (e.key === 'Backspace' && !tagInput.value && state.tags.length) { state.tags.pop(); renderChips(); }
  });
  tagChips.addEventListener('click', (e) => {
    const x = e.target.closest('[data-chip]');
    if (x) { state.tags.splice(Number(x.dataset.chip), 1); renderChips(); }
  });

  // ── type picker + the add/remove-row buttons + submit/close (delegated) ──
  backdrop.addEventListener('click', onClick);
  function onClick(e) {
    // close (X, cancel, or backdrop)
    if (e.target.closest('[data-close]')) { close(); return; }
    if (e.target === backdrop) { close(); return; }

    // type radios are handled on 'change' below; here we catch the +/- row buttons.
    // Snapshot the scalar fields first so a row add/remove never wipes typed values.
    // paintFields() rebuilds fieldsHost via innerHTML, destroying the +/× button the user
    // pressed — so after each repaint we move focus to a sensible remaining control so the
    // keyboard user isn't dropped to <body>.
    if (e.target.closest('[data-add-list]')) {
      const s = snapshotScalars();
      state.listRows.push({ text: '', note: '' });
      paintFields(s);
      focusNewListRow();
      return;
    }
    const delList = e.target.closest('[data-del-list]');
    if (delList) {
      const i = Number(delList.dataset.delList);
      if (state.listRows.length > 1) {
        const s = snapshotScalars();
        state.listRows.splice(i, 1);
        paintFields(s);
        focusAfterRemove('[data-del-list]', '[data-add-list]');
      }
      return;
    }
    if (e.target.closest('[data-add-opt]')) {
      const s = snapshotScalars();
      state.scnOptions.push('');
      paintFields(s);
      focusNewOptRow();
      return;
    }
    const delOpt = e.target.closest('[data-del-opt]');
    if (delOpt) {
      const i = Number(delOpt.dataset.delOpt);
      if (state.scnOptions.length > 2) {
        const s = snapshotScalars();
        state.scnOptions.splice(i, 1);
        if (state.scnCorrect >= state.scnOptions.length) state.scnCorrect = state.scnOptions.length - 1;
        paintFields(s);
        focusAfterRemove('[data-del-opt]', '[data-add-opt]');
      }
      return;
    }
    if (e.target.closest('[data-submit]')) { submit(); return; }
  }

  // After ADD: focus the new row's first text input so the user can keep typing.
  function focusNewListRow() {
    const rows = fieldsHost.querySelectorAll('[data-list-row]');
    const last = rows[rows.length - 1];
    const input = last && last.querySelector('[name="li-text"]');
    if (input) input.focus();
  }
  function focusNewOptRow() {
    const rows = fieldsHost.querySelectorAll('[data-scn-opt]');
    const last = rows[rows.length - 1];
    const input = last && last.querySelector('[name="scn-opt-text"]');
    if (input) input.focus();
  }
  // After REMOVE: focus the nearest remaining delete (×) button, or the "+ Add" button if
  // none remain enabled. delSel finds the ×s; addSel finds the add button as a fallback.
  function focusAfterRemove(delSel, addSel) {
    const dels = [...fieldsHost.querySelectorAll(delSel)].filter((b) => !b.disabled);
    const target = dels[dels.length - 1] || fieldsHost.querySelector(addSel);
    if (target) target.focus();
  }

  backdrop.addEventListener('change', (e) => {
    const typeRadio = e.target.closest('[name="composer-type"]');
    if (typeRadio) { state.type = typeRadio.value; paintFields(); }
  });

  // ── focus trap + ESC ──
  // Bound to `document` (not the backdrop) so Tab-trap + ESC keep working even when focus
  // has moved outside the backdrop subtree. close() removes this same document listener.
  function onKeydown(e) {
    if (closed) return; // stray event during teardown — do nothing
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key !== 'Tab') return;
    const focusables = [...backdrop.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  document.addEventListener('keydown', onKeydown);

  // ── submit ──
  async function submit() {
    clearErrors();
    let sess;
    try { sess = requireSession(); }
    catch (err) { close(); if (onPosted) onPosted({ toast: 'Sign in to post.', tone: 'error' }); return; }

    // Keep any pending media-input edits in sync before reading.
    rebuildMediaFromInputs();
    // Read the live per-type field values straight from the DOM at submit time.
    state._readPayload = () => readPayloadFrom(backdrop, state);
    const item = buildItem(state, sess);

    const verdict = await validateFeedItem(item);
    if (!verdict.ok) { showErrors(verdict.errors); return; }

    let posted = false;
    try {
      await createPost(item);
      posted = true;
    } catch (err) {
      // Defensive — inline validation passed, so this should not happen. Show it anyway.
      summary.textContent = (err && err.message) ? err.message : 'Could not post. Please try again.';
      summary.classList.add('show');
      return;
    }
    if (posted) { close(); if (onPosted) onPosted({ toast: 'Posted.', tone: 'ok', item }); }
  }

  // Map a validator error path → a field element and mark it; collect a summary line list.
  function showErrors(errors) {
    const lines = [];
    for (const err of errors) {
      lines.push(err.message);
      const field = fieldForPath(err.path);
      if (field) {
        field.classList.add('has-error');
        const msgEl = field.querySelector('.composer-err');
        if (msgEl) msgEl.textContent = err.message;
      }
    }
    summary.innerHTML = `<strong>Could not post.</strong> ` +
      `<ul>${lines.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`;
    summary.classList.add('show');
    // move focus to the summary so it's announced and reachable
    summary.focus();
  }

  function clearErrors() {
    summary.textContent = '';
    summary.classList.remove('show');
    backdrop.querySelectorAll('.has-error').forEach((f) => {
      f.classList.remove('has-error');
      const m = f.querySelector('.composer-err'); if (m) m.textContent = '';
    });
  }

  // Resolve a validator path (e.g. "/body", "/items/0/text") to the nearest labelled
  // field block. Falls back to null (summary still lists it).
  function fieldForPath(path) {
    if (!path) return null;
    const key = path.replace(/^\//, '').split('/')[0];
    // direct name match within the dialog
    const byName = backdrop.querySelector(`[data-field="${key}"]`);
    if (byName) return byName;
    // common aliases
    const alias = { items: 'items', options: 'options', durationSec: 'durationSec', correct: 'options' };
    if (alias[key]) return backdrop.querySelector(`[data-field="${alias[key]}"]`);
    return null;
  }

  // ── close + cleanup (no listener leak across opens) ──
  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    backdrop.removeEventListener('click', onClick);
    document.removeEventListener('keydown', onKeydown);
    backdrop.remove();
    document.body.classList.remove('composer-open');
    if (returnFocusTo && typeof returnFocusTo.focus === 'function') returnFocusTo.focus();
  }

  // first paint + initial focus
  paintFields();
  renderChips();
  // focus the first interactive element (the type picker) for keyboard users
  const firstFocus = backdrop.querySelector(FOCUSABLE);
  if (firstFocus) firstFocus.focus();

  return { close };
}

// ── item builder ─────────────────────────────────────────────────────────────────
// Turns editor state + the session into a schema-shaped item. frameworkRef is set ONLY
// when a real category (not 'other') is chosen — never sent as ''. Numbers are coerced
// to integers. media[] only when a usable media item exists.
function buildItem(state, session) {
  const now = new Date().toISOString();
  const author = {
    userId: session.userId,
    name: session.name
  };
  if (session.initials) author.initials = session.initials;
  if (session.role) author.role = session.role;

  const item = {
    id: newId(),
    type: state.type,
    author,
    // status: 'published' for this UI pass. The backend lifecycle is pending-review →
    // published; client-only, we publish straight away so the post appears in the stream.
    status: 'published',
    topics: state.tags.slice(),
    createdAt: now,
    updatedAt: now,
    engagement: { upvotes: 0, comments: 0, saves: 0 }
  };

  // frameworkRef only when categorised (a real letter), never '' for "Other".
  if (state.categoryId && state.categoryId !== 'other') item.frameworkRef = state.categoryId;

  // per-type payload — read from the live DOM fields via the captured field-reader
  Object.assign(item, state._readPayload ? state._readPayload() : {});

  // media (URL only this pass). Drop empties so we never send a broken media item.
  const m = cleanMedia(state.media);
  if (m) item.media = [m];

  return item;
}

// Keep only a complete media item; otherwise return null (so media[] is omitted).
function cleanMedia(m) {
  if (!m) return null;
  if (m.kind === 'image') return m.url ? { kind: 'image', url: m.url, alt: m.alt || '' } : null;
  if (m.kind === 'diagram') {
    if (m.render === 'image') return m.url ? { kind: 'diagram', render: 'image', url: m.url, alt: m.alt || '' } : null;
    return m.source ? { kind: 'diagram', render: m.render, source: m.source, alt: m.alt || '' } : null;
  }
  return null;
}

// ── HTML builders ────────────────────────────────────────────────────────────────
function shellHTML(categories) {
  return `<div class="composer" role="dialog" aria-modal="true" aria-labelledby="composer-h">
    <div class="composer-bar">
      <h2 id="composer-h" class="composer-h">New post</h2>
      <button type="button" class="composer-x" data-close aria-label="Close">×</button>
    </div>
    <div class="composer-scroll">
      <div class="composer-summary" role="alert" aria-live="assertive" tabindex="-1"></div>

      <fieldset class="composer-types">
        <legend>Type</legend>
        <div class="composer-typestrip" role="radiogroup" aria-label="Post type">
          ${TYPES.map((t, i) => `<label class="composer-type">
            <input type="radio" name="composer-type" value="${t.id}"${i === 0 ? ' checked' : ''}>
            <span>${esc(t.label)}</span></label>`).join('')}
        </div>
      </fieldset>

      <div class="composer-row" data-field="category">
        <label for="composer-cat">Categorise <span class="composer-opt">(optional)</span></label>
        ${categorySelectHTML(categories)}
      </div>

      <div class="composer-row" data-field="topics">
        <label for="composer-tag">Tags <span class="composer-opt">(optional)</span></label>
        <div class="composer-chips" aria-live="polite"></div>
        <input id="composer-tag" name="tag-input" type="text" class="composer-input"
          placeholder="Type a tag, press Enter" autocomplete="off">
        <p class="composer-hint">Lowercased and de-duped. These become the post's topics.</p>
      </div>

      <div data-fields></div>
    </div>
    <div class="composer-foot">
      <button type="button" class="composer-cancel" data-close>Cancel</button>
      <button type="button" class="composer-post" data-submit>Post</button>
    </div>
  </div>`;
}

// Grouped <select> of framework addresses + an explicit "Other / Uncategorised" option.
function categorySelectHTML(categories) {
  const byRing = new Map();
  let other = null;
  for (const c of categories) {
    if (c.id === 'other') { other = c; continue; }
    if (!byRing.has(c.ring)) byRing.set(c.ring, []);
    byRing.get(c.ring).push(c);
  }
  let groups = '';
  for (const [ring, cats] of byRing) {
    groups += `<optgroup label="${esc(ring)}">` +
      cats.map((c) => `<option value="${esc(c.id)}">${esc(c.letter)} · ${esc(c.name)}</option>`).join('') +
      `</optgroup>`;
  }
  const otherOpt = `<option value="other" selected>${esc(other ? other.name : 'Other / Uncategorised')}</option>`;
  return `<select id="composer-cat" name="category" class="composer-input">${otherOpt}${groups}</select>`;
}

// Per-type fields. Returns HTML; the controller re-binds dynamic listeners after each paint.
function typeFieldsHTML(state, categories) {
  switch (state.type) {
    case 'post': return postFields();
    case 'video': return videoFields();
    case 'list': return listFields(state);
    case 'card': return cardFields();
    case 'vocab': return vocabFields();
    case 'scenario': return scenarioFields(state);
    default: return '';
  }
}

function row(field, name, label, opts = {}) {
  const optTag = opts.optional ? ` <span class="composer-opt">(optional)</span>` : ` <span class="composer-req" aria-hidden="true">*</span>`;
  const ph = opts.placeholder ? ` placeholder="${esc(opts.placeholder)}"` : '';
  const id = `composer-${name}`;
  const describe = ` aria-describedby="${id}-err"`;
  const control = opts.textarea
    ? `<textarea id="${id}" name="${name}" class="composer-input composer-area" rows="${opts.rows || 4}"${ph}${describe}${opts.required ? ' required' : ''}></textarea>`
    : `<input id="${id}" name="${name}" type="${opts.inputType || 'text'}" class="composer-input"${ph}${describe}${opts.min != null ? ` min="${opts.min}"` : ''}${opts.required ? ' required' : ''}>`;
  return `<div class="composer-row" data-field="${field}">
    <label for="${id}">${esc(label)}${optTag}</label>
    ${control}
    ${opts.extra || ''}
    <p class="composer-err" id="${id}-err" role="alert"></p>
  </div>`;
}

function postFields() {
  return row('title', 'title', 'Title', { optional: true, placeholder: 'Optional headline' }) +
    row('body', 'body', 'Body', {
      required: true, textarea: true, rows: 5, placeholder: 'Up to 100 words.',
      extra: `<div class="composer-counter" aria-live="polite">0 / ${WORD_CAP}</div>`
    }) +
    mediaSectionHTML();
}

function videoFields() {
  return row('title', 'title', 'Title', { required: true }) +
    row('durationSec', 'durationSec', 'Duration (seconds)', { required: true, inputType: 'number', min: 1, placeholder: 'e.g. 45' }) +
    row('hook', 'hook', 'Hook', { optional: true, textarea: true, rows: 2 }) +
    row('url', 'url', 'Video URL', { optional: true, placeholder: 'https://…' }) +
    mediaSectionHTML();
}

function listFields(state) {
  const rows = state.listRows.map((r, i) => `
    <div class="composer-listrow" data-list-row="${i}">
      <div class="composer-listrow-fields">
        <input name="li-text" class="composer-input" placeholder="Item text" value="${esc(r.text)}" aria-label="List item ${i + 1} text">
        <input name="li-note" class="composer-input composer-input-note" placeholder="Note (optional)" value="${esc(r.note)}" aria-label="List item ${i + 1} note">
      </div>
      <button type="button" class="composer-rowdel" data-del-list="${i}" aria-label="Remove item ${i + 1}"${state.listRows.length <= 1 ? ' disabled' : ''}>×</button>
    </div>`).join('');
  return row('title', 'title', 'Title', { required: true }) +
    row('intro', 'intro', 'Intro', { optional: true, textarea: true, rows: 2 }) +
    `<div class="composer-row" data-field="items">
      <label>Items <span class="composer-req" aria-hidden="true">*</span></label>
      <div class="composer-rows">${rows}</div>
      <button type="button" class="composer-addrow" data-add-list>+ Add item</button>
      <p class="composer-err" id="composer-items-err" role="alert"></p>
    </div>` +
    mediaSectionHTML();
}

function cardFields() {
  return row('title', 'title', 'Title', { required: true }) +
    row('teaser', 'teaser', 'Teaser', { required: true, textarea: true, rows: 3 }) +
    row('linkUrl', 'linkUrl', 'Link URL', { optional: true, placeholder: 'https://…' }) +
    mediaSectionHTML();
}

function vocabFields() {
  return row('term', 'term', 'Term', { required: true }) +
    row('definition', 'definition', 'Definition', { required: true, textarea: true, rows: 4 }) +
    mediaSectionHTML();
}

function scenarioFields(state) {
  const opts = state.scnOptions.map((o, i) => `
    <div class="composer-optrow" data-scn-opt="${i}">
      <label class="composer-correct">
        <input type="radio" name="scn-correct" value="${i}"${state.scnCorrect === i ? ' checked' : ''} aria-label="Mark option ${i + 1} correct">
      </label>
      <input name="scn-opt-text" class="composer-input" placeholder="Option ${i + 1}" value="${esc(o)}" aria-label="Option ${i + 1} text">
      <button type="button" class="composer-rowdel" data-del-opt="${i}" aria-label="Remove option ${i + 1}"${state.scnOptions.length <= 2 ? ' disabled' : ''}>×</button>
    </div>`).join('');
  return row('prompt', 'prompt', 'Prompt', { required: true, textarea: true, rows: 3 }) +
    `<div class="composer-row" data-field="options">
      <label>Options <span class="composer-req" aria-hidden="true">*</span> <span class="composer-opt">(tick the correct one)</span></label>
      <div class="composer-rows" role="radiogroup" aria-label="Options; tick the correct one">${opts}</div>
      <button type="button" class="composer-addrow" data-add-opt>+ Add option</button>
      <p class="composer-err" id="composer-options-err" role="alert"></p>
    </div>` +
    row('verdict', 'verdict', 'Verdict', { required: true, placeholder: 'The one-line answer' }) +
    row('reveal', 'reveal', 'Reveal', { required: true, textarea: true, rows: 3, placeholder: 'The explanation shown after answering' }) +
    mediaSectionHTML();
}

// The optional, collapsible media sub-form (URL only this pass).
function mediaSectionHTML() {
  return `<details class="composer-media">
    <summary>Attach media <span class="composer-opt">(optional)</span></summary>
    <div class="composer-row">
      <label for="composer-media-kind">Media type</label>
      <select id="composer-media-kind" name="media-kind" class="composer-input">
        <option value="">None</option>
        <option value="image">Image</option>
        <option value="diagram">Diagram</option>
      </select>
    </div>
    <div data-media-sub></div>
    <div class="composer-media-preview" aria-live="polite"></div>
  </details>`;
}

// The kind-specific media sub-fields. image → url + alt; diagram → render + source/url + alt.
function mediaSubHTML(kind) {
  if (kind === 'image') {
    return `<div class="composer-row">
        <label for="composer-media-url">Image URL</label>
        <input id="composer-media-url" name="media-url" data-media-field class="composer-input" placeholder="https://…">
      </div>
      <div class="composer-row">
        <label for="composer-media-alt">Alt text</label>
        <input id="composer-media-alt" name="media-alt" data-media-field class="composer-input" placeholder="Describe the image">
      </div>`;
  }
  if (kind === 'diagram') {
    return `<div class="composer-row">
        <label for="composer-media-render">Render</label>
        <select id="composer-media-render" name="media-render" data-media-field class="composer-input">
          <option value="mermaid">Mermaid</option>
          <option value="ascii">ASCII</option>
          <option value="image">Image (URL)</option>
        </select>
      </div>
      <div class="composer-row">
        <label for="composer-media-source">Source <span class="composer-opt">(for mermaid / ASCII)</span></label>
        <textarea id="composer-media-source" name="media-source" data-media-field class="composer-input composer-area" rows="3" placeholder="graph TD; A--&gt;B"></textarea>
      </div>
      <div class="composer-row">
        <label for="composer-media-url">URL <span class="composer-opt">(for render = image)</span></label>
        <input id="composer-media-url" name="media-url" data-media-field class="composer-input" placeholder="https://…">
      </div>
      <div class="composer-row">
        <label for="composer-media-alt">Alt text</label>
        <input id="composer-media-alt" name="media-alt" data-media-field class="composer-input" placeholder="Describe the diagram">
      </div>`;
  }
  return '';
}

// ── payload reader ───────────────────────────────────────────────────────────────
// buildItem() needs the live per-type field values. We read them straight from the DOM
// at submit time (the dynamic listeners already keep the array-shaped state in sync, but
// the simple inputs are read here so we always reflect the latest typed value).
// This function is attached to state by the controller right before submit.
//
// REQUIRED-FIELD DISCIPLINE: the schema's `required` is satisfied by a present key even
// if its value is "" (empty string is a valid `type: string`). So a blank required field
// would otherwise sneak through. We therefore OMIT a required string field when it is
// blank — the schema then reports a clean "missing required field" error, which the
// composer maps back to the field. (Truly optional fields are already omitted when blank.)
export function readPayloadFrom(backdrop, state) {
  const v = (name) => { const el = backdrop.querySelector(`[name="${name}"]`); return el ? el.value : ''; };
  // setReq(out, key, value): include only if non-blank, so blank required fields fail
  // validation as "missing" rather than persisting as an empty string.
  const setReq = (out, key, value) => { const s = (value || '').trim(); if (s) out[key] = s; };
  const t = state.type;
  if (t === 'post') {
    const out = {};
    setReq(out, 'body', v('body'));           // required; blank → omitted → schema flags missing
    const title = v('title').trim(); if (title) out.title = title; // optional
    return out;
  }
  if (t === 'video') {
    const out = {};
    setReq(out, 'title', v('title'));
    const dur = parseInt(v('durationSec'), 10);
    if (!Number.isNaN(dur)) out.durationSec = dur; // blank/NaN → omitted → schema flags missing
    const hook = v('hook').trim(); if (hook) out.hook = hook;
    const url = v('url').trim(); if (url) out.url = url;
    return out;
  }
  if (t === 'list') {
    const out = {};
    setReq(out, 'title', v('title'));
    const intro = v('intro').trim(); if (intro) out.intro = intro;
    out.items = state.listRows
      .map((r) => { const o = { text: (r.text || '').trim() }; if ((r.note || '').trim()) o.note = r.note.trim(); return o; })
      .filter((r) => r.text);
    // an empty items[] would still fail the schema's minItems:1 — leave it as-is so the
    // error surfaces rather than silently dropping the key.
    return out;
  }
  if (t === 'card') {
    const out = {};
    setReq(out, 'title', v('title'));
    setReq(out, 'teaser', v('teaser'));
    const link = v('linkUrl').trim(); if (link) out.linkUrl = link;
    return out;
  }
  if (t === 'vocab') {
    const out = {};
    setReq(out, 'term', v('term'));
    setReq(out, 'definition', v('definition'));
    return out;
  }
  if (t === 'scenario') {
    const out = {
      options: state.scnOptions.map((o) => (o || '').trim()).filter(Boolean),
      correct: state.scnCorrect
    };
    setReq(out, 'prompt', v('prompt'));
    setReq(out, 'verdict', v('verdict'));
    setReq(out, 'reveal', v('reveal'));
    return out;
  }
  return {};
}
