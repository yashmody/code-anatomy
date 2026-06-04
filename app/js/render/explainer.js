// Framework Explainer — the 10 static framing pieces (masthead, Part banners, CODE/CODER
// wrappers + telescopes, four CODE node-blocks, three CODER letter intros, the #nest
// triple-telescope, the Executive Review Model, and the "Who watches what" table).
//
// VERBATIM RE-SHELL. The body strings live in content-architecture/course/framework-explainer.json
// and were copied character-for-character from content-system/anatomy-of-code-course.html.
// These renderers emit the SAME HTML shape as the monolith so the existing monolith.css
// classes (.telescope, .scope, .letters, .letter, .node-block, .dims, .ask, .chips,
// .nest-arrow, .review, .rev-card, .watch, .part-head, .mod-tag, .masthead, .kicker, etc.)
// style them automatically — no new CSS required.
//
// Use raw() for prose that may contain <strong>/<em>/<b>/&entities; — esc() for plain text
// fields (glyphs, names, chips, table cells).

import { raw, esc } from '../util/dom.js';

// ────────────────────────────────────────────────────────────────────────────
// Helpers — letter card (used by every .telescope and by #nest's scopes)
// ────────────────────────────────────────────────────────────────────────────
function letterCard(L, opts) {
  opts = opts || {};
  const glyphStyle = L.glyphStyle ? ` style="${esc(L.glyphStyle)}"` : '';
  const nameStyle  = L.nameStyle  ? ` style="${esc(L.nameStyle)}"`  : '';
  // glyph: in CODE/CODER mode it's a single letter; in #nest "word" mode it's a word.
  const glyph = `<div class="glyph"${glyphStyle}>${esc(L.glyph || '')}</div>`;
  const name  = L.name  ? `<div class="lname"${nameStyle}>${raw(L.name)}</div>` : '';
  const desc  = L.desc  ? `<div class="ldesc">${raw(L.desc)}</div>`             : '';
  return `<div class="letter">${glyph}${name}${desc}</div>`;
}

function telescopeScope(scope) {
  const cls   = `scope${scope.inner ? ' inner' : ''}`;
  const sty   = scope.style ? ` style="${esc(scope.style)}"` : '';
  const lblSt = scope.labelStyle ? ` style="${esc(scope.labelStyle)}"` : '';
  const lbl   = scope.label ? `<div class="scope-label"${lblSt}>${esc(scope.label)}</div>` : '';
  const cards = (scope.letters || []).map((L) => letterCard(L)).join('');
  return `<div class="${cls}"${sty}>${lbl}<div class="letters">${cards}</div></div>`;
}

// ────────────────────────────────────────────────────────────────────────────
// 1. MASTHEAD — the course header. We keep the existing app-bar above this in
//    index.html; the masthead is the canonical title block from the monolith.
//    Source: lines 679–708 of content-system/anatomy-of-code-course.html.
// ────────────────────────────────────────────────────────────────────────────
export function renderMasthead(d) {
  const meta = (d.meta || []).map((m) => `<span>${raw(m.html)}</span>`).join('');
  return (
    `<header class="masthead explainer-masthead">` +
      `<div class="kicker">${esc(d.kicker || '')}</div>` +
      `<h1 class="title">${raw(d.title || '')}</h1>` +
      `<p class="subtitle">${raw(d.subtitle || '')}</p>` +
      (meta ? `<div class="meta-row">${meta}</div>` : '') +
    `</header>`
  );
}

// ────────────────────────────────────────────────────────────────────────────
// 2. PART BANNER — Part One / Two / Three dividers.
//    Sources: lines 747–751 (Part One), 4248–4252 (Part Two), 5450–5455 (Part Three).
// ────────────────────────────────────────────────────────────────────────────
export function renderPartBanner(p) {
  if (!p) return '';
  return (
    `<div class="part-head explainer-partbanner">` +
      `<div class="pno">${esc(p.no || '')}</div>` +
      `<h2>${raw(p.title || '')}</h2>` +
      `<p>${raw(p.body || '')}</p>` +
    `</div>`
  );
}

// ────────────────────────────────────────────────────────────────────────────
// 3. CODE OUTER LENS — section wrapper + the 4-letter telescope.
//    Source: lines 754–780.
// ────────────────────────────────────────────────────────────────────────────
export function renderCodeOuter(d) {
  const tel = d.telescope || {};
  return (
    `<section class="module explainer-module" id="${esc(d.id || 'code')}">` +
      `<div class="mod-tag">${esc(d.modTag || '')}</div>` +
      `<h3>${raw(d.heading || '')}</h3>` +
      `<p>${raw(d.intro || '')}</p>` +
      `<div class="telescope">` +
        telescopeScope({
          label: tel.label,
          letters: tel.letters || []
        }) +
      `</div>` +
    `</section>`
  );
}

// ────────────────────────────────────────────────────────────────────────────
// 4. CODE NODE-BLOCK — one per C / O / D / E inside CODE.
//    Sources:
//      C · Content:          lines 783–808  (8 dims + 5 asks + 8 chips, accent rail)
//      O · Operations:       lines 953–966  (3 asks + 6 chips)
//      D · Design & Data:    lines 1127–1145 (2 ask-groups + 8 chips)
//      E · Engineering:      lines 1420–1427 (intro p + 3 chips, no asks)
// ────────────────────────────────────────────────────────────────────────────
export function renderNodeBlock(letterKey, n) {
  if (!n) return '';
  const cls = `node-block explainer-nodeblock${n.accent ? ' accent' : ''}`;

  // Dims grid (only C uses it)
  let dimsHTML = '';
  if (n.dims && n.dims.length) {
    const tiles = n.dims.map((d) =>
      `<div class="dim"><b>${esc(d.title || '')}</b><span>${raw(d.desc || '')}</span></div>`
    ).join('');
    dimsHTML = `<div class="dims">${tiles}</div>`;
  }

  // Ask lists — either a single { asks[] } or multiple { askGroups[] } (D uses groups)
  let asksHTML = '';
  if (n.askGroups && n.askGroups.length) {
    asksHTML = n.askGroups.map((g) =>
      `<div class="ask-label">${esc(g.label || '')}</div>` +
      `<ul class="ask">${(g.items || []).map((q) => `<li>${raw(q)}</li>`).join('')}</ul>`
    ).join('');
  } else if (n.asks && n.asks.length) {
    asksHTML =
      (n.asksLabel ? `<div class="ask-label">${esc(n.asksLabel)}</div>` : '') +
      `<ul class="ask">${n.asks.map((q) => `<li>${raw(q)}</li>`).join('')}</ul>`;
  }

  // Deliverables chips
  let chipsHTML = '';
  if (n.deliverables && n.deliverables.length) {
    chipsHTML =
      `<div class="ask-label">Deliverables</div>` +
      `<div class="chips">` +
        n.deliverables.map((c) => `<span>${raw(c)}</span>`).join('') +
      `</div>`;
  }

  return (
    `<div class="${cls}">` +
      `<div class="rail"><div class="rg">${esc(n.rail || letterKey.toUpperCase())}</div>` +
        `<div class="rn">${raw(n.name || '')}</div></div>` +
      `<div class="nb-body">` +
        (n.intro ? `<p>${raw(n.intro)}</p>` : '') +
        dimsHTML +
        asksHTML +
        chipsHTML +
      `</div>` +
    `</div>`
  );
}

// ────────────────────────────────────────────────────────────────────────────
// 5. CODER INNER LENS — section wrapper + 5-letter inner telescope + "What
//    each layer asks" + the closing blockquote.
//    Source: lines 1431–1470.
// ────────────────────────────────────────────────────────────────────────────
export function renderCoderInner(d) {
  const tel = d.telescope || {};
  const asks = (d.asks || []).map((a) => `<li>${raw(a.html || a)}</li>`).join('');
  return (
    `<section class="module explainer-module" id="${esc(d.id || 'coder')}">` +
      `<div class="mod-tag">${esc(d.modTag || '')}</div>` +
      `<h3>${raw(d.heading || '')}</h3>` +
      `<p>${raw(d.intro || '')}</p>` +
      `<div class="telescope">` +
        telescopeScope({
          inner: tel.inner,
          label: tel.label,
          labelStyle: 'color:var(--ochre-deep)',
          letters: tel.letters || []
        }) +
      `</div>` +
      (d.asksLabel ? `<div class="ask-label">${esc(d.asksLabel)}</div>` : '') +
      (asks ? `<ul class="ask">${asks}</ul>` : '') +
      (d.blockquote ? `<blockquote>${raw(d.blockquote)}</blockquote>` : '') +
    `</section>`
  );
}

// ────────────────────────────────────────────────────────────────────────────
// 6. CODER WRAPPER — the short intro section before coder.o / coder.e / coder.r.
//    Sources: 3068–3072 (O), 3381–3385 (E), 3709–3713 (R).
// ────────────────────────────────────────────────────────────────────────────
export function renderCoderWrapper(letter, w) {
  if (!w) return '';
  return (
    `<section class="module explainer-module" id="${esc(w.id || ('coder-' + letter))}">` +
      `<div class="mod-tag">${esc(w.modTag || '')}</div>` +
      `<h3>${raw(w.heading || '')}</h3>` +
      `<p>${raw(w.body || '')}</p>` +
    `</section>`
  );
}

// ────────────────────────────────────────────────────────────────────────────
// 7. NEST — the punchline. Three nested scopes (CODE → CODER → Anatomy of Code)
//    with "Engineering opens up" / "Code opens up" arrows between them.
//    Source: lines 4169–4206.
// ────────────────────────────────────────────────────────────────────────────
export function renderNest(d) {
  const scopes = d.scopes || [];
  const arrows = d.arrows || [];
  let inner = '';
  scopes.forEach((s, i) => {
    inner += telescopeScope(s);
    if (i < scopes.length - 1 && arrows[i]) {
      inner += `<div class="nest-arrow"><span>${esc(arrows[i])}</span></div>`;
    }
  });
  return (
    `<section class="module explainer-module" id="${esc(d.id || 'nest')}">` +
      `<div class="mod-tag">${esc(d.modTag || '')}</div>` +
      `<h3>${raw(d.heading || '')}</h3>` +
      `<p>${raw(d.intro || '')}</p>` +
      `<div class="telescope">${inner}</div>` +
      (d.blockquote ? `<blockquote>${raw(d.blockquote)}</blockquote>` : '') +
    `</section>`
  );
}

// ────────────────────────────────────────────────────────────────────────────
// 8. EXECUTIVE REVIEW MODEL — 8 cards × 3 questions each.
//    Source: lines 4209–4224.
// ────────────────────────────────────────────────────────────────────────────
export function renderReview(d) {
  const cards = (d.cards || []).map((c) =>
    `<div class="rev-card">` +
      `<h5>${raw(c.name || '')}</h5>` +
      `<ul>${(c.questions || []).map((q) => `<li>${raw(q)}</li>`).join('')}</ul>` +
    `</div>`
  ).join('');
  return (
    `<section class="module explainer-module" id="${esc(d.id || 'review')}">` +
      `<div class="mod-tag">${esc(d.modTag || '')}</div>` +
      `<h3>${raw(d.heading || '')}</h3>` +
      `<p>${raw(d.intro || '')}</p>` +
      `<div class="review">${cards}</div>` +
      (d.blockquote ? `<blockquote>${raw(d.blockquote)}</blockquote>` : '') +
    `</section>`
  );
}

// ────────────────────────────────────────────────────────────────────────────
// 9. WHO WATCHES WHAT — 3-col, 8-row oversight table.
//    Source: lines 4227–4245.
// ────────────────────────────────────────────────────────────────────────────
export function renderWatch(d) {
  const heads = (d.headers || []).map((h) => `<th scope="col">${raw(h)}</th>`).join('');
  const rows  = (d.rows || []).map((r) =>
    `<tr><td>${raw(r.node || '')}</td><td>${raw(r.architect || '')}</td><td>${raw(r.pm || '')}</td></tr>`
  ).join('');
  return (
    `<section class="module explainer-module" id="${esc(d.id || 'watch')}">` +
      `<div class="mod-tag">${esc(d.modTag || '')}</div>` +
      `<h3>${raw(d.heading || '')}</h3>` +
      `<p>${raw(d.intro || '')}</p>` +
      `<table class="watch">` +
        `<thead><tr>${heads}</tr></thead>` +
        `<tbody>${rows}</tbody>` +
      `</table>` +
      (d.blockquote ? `<blockquote>${raw(d.blockquote)}</blockquote>` : '') +
    `</section>`
  );
}
