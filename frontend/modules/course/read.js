// READ mode — the ebook. Same authored content as Scroll, grouped into turnable pages
// by the `page` flag, one chapter per framework letter, with a telescope transition
// generated from `opensInto`. Reuses the exact same block renderers as Scroll.
//
// VISUAL PARITY pass: a warm read-paper surface, a merged reference-style opener
// (breadcrumb + big letter + drop-cap lede + scan panel), Newsreader reading body
// (re-skinned via scoped CSS), a telescope transition page, and page-dot navigation
// with a slide-in transition + swipe + Prev/Next + arrow keys. All presentation;
// the data logic (framework load, section load, opensInto, nextLetter, routing) is
// unchanged. Styling is scoped under `.read` so Manual stays byte-identical.
import { loadFramework, indexFramework } from '../../shared/framework.js';
import { loadJSON } from '../../core/api-client.js';
import { renderBlock } from '../../shared/registry.js';
import { renderScanBox } from '../../shared/render/chapter.js';
import { runMermaid } from '../../shared/render/diagram.js';
import { esc } from '../../shared/dom.js';
import {
  renderMasthead, renderPartBanner, renderCodeOuter, renderNodeBlock,
  renderCoderInner, renderCoderWrapper, renderNest, renderReview, renderWatch
} from '../../shared/render/explainer.js';

const SELF_HEADED = new Set(['chapter-open', 'heading', 'architects-review']);
let activeKeyHandler = null;

function nextLetter(idx, address) {
  const i = idx.order.indexOf(address);
  for (let j = i + 1; j < idx.order.length; j++) {
    const n = idx.byId[idx.order[j]];
    if (n && n.kind === 'letter') return n;
  }
  return null;
}

// The first child of a ring (lowest order) — where a "Descend into <RING>" lands.
// A ring carries either letters (CODE/CODER) or modules (Anatomy); take whichever it has.
function firstChildOf(idx, ringId) {
  const ring = idx.byId[ringId];
  if (!ring) return null;
  const kids = ((ring.letters && ring.letters.length ? ring.letters : ring.modules) || [])
    .slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  return kids[0] ? idx.byId[kids[0].id] : null;
}

// Breadcrumb down the nesting chain: CODE › E › CODER › D. Each ring contributes a
// pair <ring name> › <letter>; outer rings come first, this chapter's letter last.
function breadcrumb(idx, node) {
  const pairs = [];
  let ring = idx.byId[node.ringId];
  // innermost pair first: <this ring name> › <this letter>
  if (ring) pairs.unshift([esc(ring.name || ''), esc(node.letter || '')]);
  // climb outward: the ring may be nestedUnder a letter in an outer ring.
  let guard = 0;
  while (ring && ring.nestedUnder && guard++ < 8) {
    const parentLetter = idx.byId[ring.nestedUnder];
    if (!parentLetter) break;
    const parentRing = idx.byId[parentLetter.ringId];
    pairs.unshift([esc(parentRing ? parentRing.name || '' : ''), esc(parentLetter.letter || '')]);
    ring = parentRing;
  }
  return pairs.flat().filter(Boolean).join(' › ');
}

// ════════════════════════════════════════════════════════════════════════════
// Dispatcher: no address → the Contents library; an address → the chapter reader.
// SECTION_FILES (from main.js) tells Contents which chapters actually have a file,
// so we never link a row to a 404 (e.g. anatomy.m12 — Stalwart lives in coder.c).
// ════════════════════════════════════════════════════════════════════════════
export async function renderRead(mount, base, address, sectionFile, sectionFiles) {
  if (!address) return renderContents(mount, base, sectionFiles || []);
  if (address === 'framework') return renderFrameworkExplainer(mount, base);
  return renderChapter(mount, base, address, sectionFile);
}

// ── CONTENTS LIBRARY ──────────────────────────────────────────────────────────
// A scannable table of contents: the 5 framework rings (in framework order), each
// a collapsible category, listing only its chapters that have a section file. Pure
// framework.json + SECTION_FILES — we do NOT fetch every chapter JSON for a count.
async function renderContents(mount, base, sectionFiles) {
  const fw = await loadFramework(base);
  const idx = indexFramework(fw);

  // 'coder-d.json' → 'coder.d' (replace the FIRST '-' only, matching the filename rule).
  const haveAddr = new Set(
    sectionFiles.map((f) => f.replace(/\.json$/, '').replace('-', '.'))
  );

  const cats = fw.rings.map((ring) => {
    const kids = ((ring.letters && ring.letters.length ? ring.letters : ring.modules) || [])
      .slice().sort((a, b) => (a.order || 0) - (b.order || 0))
      .filter((k) => haveAddr.has(k.id));
    return { ring, kids };
  }).filter((c) => c.kids.length);

  function rowHTML(ring, k) {
    const mark = esc(k.letter || (k.name || '').charAt(0) || '·');
    const meta = k.desc ? `<span class="rc-meta">${esc(k.desc)}</span>` : '';
    return `<a class="read-chrow" href="#/read/${esc(k.id)}">` +
      `<span class="rc-mark" aria-hidden="true">${mark}</span>` +
      `<span class="rc-body"><span class="rc-title">${esc(k.name)}</span>${meta}</span>` +
      `<span class="rc-go" aria-hidden="true">→</span>` +
    `</a>`;
  }

  const groups = cats.map((c, gi) => {
    const ring = c.ring;
    const panelId = `read-cat-${esc(ring.id)}`;
    const sub = ring.subtitle ? `<span class="rcat-sub">${esc(ring.subtitle)}</span>` : '';
    return `<section class="read-cat" data-ring="${esc(ring.id)}">` +
      `<button type="button" class="rcat-head" aria-expanded="true" aria-controls="${panelId}">` +
        `<span class="rcat-mark" aria-hidden="true">${gi + 1}</span>` +
        `<span class="rcat-titles"><span class="rcat-name">${esc(ring.name)}</span>${sub}</span>` +
        `<span class="rcat-count">${c.kids.length} chapter${c.kids.length === 1 ? '' : 's'}</span>` +
        `<span class="rcat-chev" aria-hidden="true">▾</span>` +
      `</button>` +
      `<div class="rcat-panel" id="${panelId}">` +
        c.kids.map((k) => rowHTML(ring, k)).join('') +
      `</div>` +
    `</section>`;
  }).join('');

  // "The Framework" — a static top entry above the 5 ring categories. Routes to the
  // paginated framework explainer (#/read/framework). Not part of SECTION_FILES; not
  // counted against any ring; its own thing.
  const frameworkEntry =
    `<section class="read-cat read-cat-framework" data-ring="framework">` +
      `<a class="read-chrow rc-framework" href="#/read/framework">` +
        `<span class="rc-mark" aria-hidden="true">◆</span>` +
        `<span class="rc-body">` +
          `<span class="rc-title">The Framework</span>` +
          `<span class="rc-meta">CODE · CODER · the nest, the review, the watch</span>` +
        `</span>` +
        `<span class="rc-go" aria-hidden="true">→</span>` +
      `</a>` +
    `</section>`;

  mount.innerHTML =
    `<div class="read read-contents">` +
      `<header class="read-toc-head">` +
        `<div class="read-toc-eyebrow">The Anatomy of Code</div>` +
        `<h1 class="read-toc-title">Contents</h1>` +
        `<p class="read-toc-lede">Choose a category, then a chapter to start reading.</p>` +
      `</header>` +
      `<div class="read-toc-list">${frameworkEntry}${groups}</div>` +
    `</div>`;

  // Collapsible categories — toggle aria-expanded + a class the CSS animates against.
  mount.querySelectorAll('.rcat-head').forEach((btn) => {
    btn.onclick = () => {
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      btn.closest('.read-cat').classList.toggle('collapsed', open);
    };
  });

  window.scrollTo(0, 0);
}

// ── CHAPTER READER ────────────────────────────────────────────────────────────
async function renderChapter(mount, base, address, sectionFile) {
  const fw = await loadFramework(base);
  const idx = indexFramework(fw);
  const sec = await loadJSON(`${base}/course/sections/${sectionFile}`);
  const node = idx.byId[address] || {};

  // Flatten blocks in sub-section order; tag the first block of each non-self-headed
  // sub-section with its title so the <h3> rides with that block onto its page.
  // PULL the chapter-open block out of the flow — it becomes the opener's drop-cap lede,
  // so it must not be duplicated on a later content page.
  const flat = [];
  let opener = null;
  const subs = (sec.sections || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  for (const sub of subs) {
    (sub.blocks || []).forEach((b, i) => {
      if (b.type === 'chapter-open' && !opener) { opener = b; return; }
      flat.push({ block: b, subTitle: (i === 0 && sub.title && !SELF_HEADED.has(b.type)) ? sub.title : null });
    });
  }

  // Group remaining blocks by `page`.
  const byPage = new Map();
  for (const item of flat) {
    const p = item.block.page || 1;
    if (!byPage.has(p)) byPage.set(p, []);
    byPage.get(p).push(item);
  }
  const pageNums = [...byPage.keys()].sort((a, b) => a - b);

  // ── SECTION → RENDERED-PAGE MAP ─────────────────────────────────────────────
  // Each sub-section's content blocks carry `page` flags (authored 1,2,3…). The
  // rendered page index of an authored page p is `1 + pageNums.indexOf(p)` (page 0
  // is the opener). A sub-section's start page = the rendered index of its lowest
  // authored page. Sub-sections whose only block became the opener (e.g. the
  // chapter-open opener section) contribute no content page and are skipped, so the
  // jump menu lists real reading destinations only.
  const sectionMap = [];   // [{ title, page }] in framework order, page = rendered index
  for (const sub of subs) {
    // "Opener" is an authoring placeholder, not a section name — its chapter-open block
    // becomes page 0; any trailing blocks belong to the brief intro page, not a named jump.
    if (sub.title && sub.title.trim().toLowerCase() === 'opener') continue;
    const authored = (sub.blocks || [])
      .filter((b) => b.type !== 'chapter-open')      // chapter-open is pulled into page 0
      .map((b) => b.page || 1);
    if (!authored.length || !sub.title) continue;
    const lo = Math.min(...authored);
    const pos = pageNums.indexOf(lo);
    if (pos < 0) continue;                            // authored page produced no rendered page
    const rendered = pos + 1;
    if (sectionMap.length && sectionMap[sectionMap.length - 1].page === rendered) continue; // de-dupe shared start
    sectionMap.push({ title: sub.title, page: rendered });
  }

  // Which sub-section owns the current page: the last section whose start page ≤ cur.
  function sectionForPage(p) {
    if (!sectionMap.length) return null;
    let found = null;
    for (let i = 0; i < sectionMap.length; i++) {
      if (sectionMap[i].page <= p) { found = sectionMap[i]; found._i = i; }
      else break;
    }
    return found;
  }

  // ── PAGE 0 — the merged opener ──────────────────────────────────────────────
  // breadcrumb eyebrow · big ochre letter · Syne chapter name · mono tag ·
  // the chapter-open drop-cap lede · a quiet "In this chapter" scan panel · a hint.
  const crumb = breadcrumb(idx, node);
  const lede = opener ? renderBlock(opener) : '';   // <p class="lead chapter-open"><span class="drop">…
  const scanPanel = sec.scan && sec.scan.length
    ? `<div class="read-scan">` +
        `<div class="read-scan-label">In this chapter</div>` +
        renderScanBox(sec.scan) +
      `</div>`
    : '';
  const openerHTML =
    `<div class="read-opener">` +
      (crumb ? `<div class="read-crumb">${crumb}</div>` : '') +
      (node.letter ? `<div class="read-bigletter" aria-hidden="true">${esc(node.letter)}</div>` : '') +
      `<h1 class="read-name">${esc(sec.title)}</h1>` +
      (sec.tag ? `<div class="read-chtag">${esc(sec.tag)}</div>` : '') +
      (lede ? `<div class="read-lede">${lede}</div>` : '') +
      scanPanel +
      `<div class="read-hint">Swipe or tap Next to read →</div>` +
    `</div>`;

  // ── CONTENT PAGES ───────────────────────────────────────────────────────────
  const contentPages = pageNums.map((p) => {
    let h = '';
    for (const item of byPage.get(p)) {
      if (item.subTitle) h += `<h3 class="sub-title">${esc(item.subTitle)}</h3>`;
      h += renderBlock(item.block);
    }
    return `<div class="read-flow">${h}</div>`;
  });

  // ── TELESCOPE / END PAGE ────────────────────────────────────────────────────
  // opensInto → descend into the nested ring; else next chapter (or end of framework).
  function endPageHTML() {
    if (node.opensInto) {
      const t = idx.byId[node.opensInto] || {};
      const target = firstChildOf(idx, node.opensInto);
      const ringName = t.name || node.opensInto;
      // the letter sequence of the target ring (e.g. M M M for Anatomy modules, or C O D E R)
      const seqSrc = (t.letters && t.letters.length ? t.letters : t.modules) || [];
      const seq = seqSrc
        .slice().sort((a, b) => (a.order || 0) - (b.order || 0))
        .map((x) => esc(x.letter || (x.name || '').charAt(0) || '·'))
        .map((ch, i) => `<span${i === 0 ? '' : ' class="dim"'}>${ch}</span>`)
        .join('');
      const cta = target
        ? `<button type="button" class="tel-btn" data-go="${esc(target.id)}">Descend into ${esc(ringName)} →</button>`
        : '';
      return `<div class="telescope">` +
        (node.letter ? `<div class="tel-from">${esc(node.letter)}</div>` : '') +
        `<div class="tel-arrow" aria-hidden="true">↓</div>` +
        `<p class="tel-msg">${esc(t.blurb || ('This chapter telescopes into ' + ringName + '.'))}</p>` +
        (seq ? `<div class="tel-into" aria-hidden="true">${seq}</div>` : '') +
        cta +
      `</div>`;
    }
    const nx = nextLetter(idx, address);
    if (nx) {
      return `<div class="telescope">` +
        `<div class="tel-eyebrow">Next chapter</div>` +
        `<p class="tel-msg"><b>${esc(nx.name)}</b></p>` +
        `<button type="button" class="tel-btn" data-go="${esc(nx.id)}">Read ${esc(nx.name)} →</button>` +
      `</div>`;
    }
    return `<div class="telescope">` +
      `<div class="tel-eyebrow">End of the framework</div>` +
      `<p class="tel-msg">You have reached the last chapter.</p>` +
    `</div>`;
  }

  // The full page list: opener + content pages + telescope/end page.
  const pages = [openerHTML, ...contentPages, endPageHTML()];
  const total = pages.length;
  let cur = 0;
  let dir = 1;    // slide direction: 1 = forward (next), -1 = back (prev)

  // Short chapters keep the familiar dot row; long ones (the new normal) get a slim
  // progress bar + a section indicator instead of an overwhelming run of dots.
  const SHORT_MAX = 8;
  const useDots = total <= SHORT_MAX;
  const hasSections = sectionMap.length >= 2;
  let drawerOpen = false;

  function goAddress(addr) {
    location.hash = '#/read/' + addr;   // main.js re-enters route() on hashchange
  }

  function dots() {
    let d = '';
    for (let i = 0; i < total; i++) {
      d += `<button type="button" class="pn-dot${i === cur ? ' on' : ''}" data-page="${i}" ` +
        `aria-label="Go to page ${i + 1} of ${total}"${i === cur ? ' aria-current="true"' : ''}></button>`;
    }
    return d;
  }

  // The Sections jump menu — one button per real reading destination.
  function drawerHTML() {
    if (!hasSections) return '';
    const items = sectionMap.map((s) => {
      const on = sectionForPage(cur) === s;
      return `<li role="none"><button type="button" role="menuitem" class="rd-item${on ? ' on' : ''}" ` +
        `data-page="${s.page}"${on ? ' aria-current="true"' : ''}>` +
        `<span class="rd-dot" aria-hidden="true"></span>${esc(s.title)}</button></li>`;
    }).join('');
    return `<div class="read-drawer" id="readDrawer" hidden>` +
      `<div class="rd-head">Sections</div>` +
      `<ul class="rd-list" role="menu" aria-label="Jump to section">${items}</ul>` +
    `</div>`;
  }

  function paint() {
    const isFirst = cur === 0;
    const isLast = cur === total - 1;
    const slide = dir >= 0 ? 'slide-next' : 'slide-prev';
    const curSec = sectionForPage(cur);
    const secLabel = curSec
      ? `${esc(curSec.title)} · Section ${curSec._i + 1} / ${sectionMap.length}`
      : `Page ${cur + 1} / ${total}`;
    const pct = total > 1 ? Math.round((cur / (total - 1)) * 100) : 100;

    const topRow =
      `<div class="read-topbar">` +
        `<a class="read-back" href="#/read" aria-label="Back to contents">← Contents</a>` +
        `<span class="read-chtitle">${esc(sec.title)}</span>` +
        (hasSections
          ? `<button type="button" class="read-sections-btn" id="readSectionsBtn" ` +
              `aria-haspopup="true" aria-expanded="${drawerOpen}" aria-controls="readDrawer">Sections ▾</button>`
          : `<span class="read-sections-spacer" aria-hidden="true"></span>`) +
      `</div>`;

    // Long chapters: progress bar + section indicator. Short chapters: dot row.
    const indicator = useDots
      ? `<div class="pn-dots" role="group" aria-label="Pages">${dots()}</div>`
      : `<div class="pn-progress">` +
          `<div class="pn-bar" aria-hidden="true"><span class="pn-bar-fill" style="width:${pct}%"></span></div>` +
          `<div class="pn-meta">${secLabel}</div>` +
        `</div>`;

    mount.innerHTML =
      `<div class="read read-reader">` +
        topRow +
        drawerHTML() +
        `<div class="read-stage">` +
          `<div class="read-page ${slide}" tabindex="-1" role="region" aria-label="Reading page">${pages[cur]}</div>` +
        `</div>` +
        `<nav class="page-nav${useDots ? '' : ' has-bar'}" aria-label="Page navigation">` +
          `<div class="page-nav-inner">` +
            `<button type="button" class="pn-btn" id="readPrev" ${isFirst ? 'disabled' : ''} aria-label="Previous page">← Prev</button>` +
            indicator +
            `<button type="button" class="pn-btn" id="readNext" ${isLast ? 'disabled' : ''} aria-label="Next page">Next →</button>` +
          `</div>` +
        `</nav>` +
        `<div class="read-live" aria-live="polite" role="status"></div>` +
      `</div>`;

    document.getElementById('readPrev').onclick = () => go(-1);
    document.getElementById('readNext').onclick = () => go(1);
    mount.querySelectorAll('.pn-dot').forEach((b) => {
      b.onclick = () => jump(parseInt(b.dataset.page, 10));
    });
    // telescope / next-chapter CTA → navigate to a real address
    const cta = mount.querySelector('[data-go]');
    if (cta) cta.onclick = () => goAddress(cta.dataset.go);

    // Sections drawer — open/close, keyboard-operable, ESC closes + restores focus.
    const secBtn = document.getElementById('readSectionsBtn');
    const drawer = document.getElementById('readDrawer');
    if (secBtn && drawer) {
      const setOpen = (open) => {
        drawerOpen = open;
        drawer.hidden = !open;
        secBtn.setAttribute('aria-expanded', String(open));
        if (open) {
          const first = drawer.querySelector('.rd-item.on') || drawer.querySelector('.rd-item');
          if (first) first.focus();
        }
      };
      secBtn.onclick = () => setOpen(!drawerOpen);
      drawer.querySelectorAll('.rd-item').forEach((b) => {
        b.onclick = () => { drawerOpen = false; jump(parseInt(b.dataset.page, 10)); };
      });
      drawer.onkeydown = (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); secBtn.focus(); }
      };
      if (drawerOpen) setOpen(true);
    }

    // swipe — left → next, right → prev (~50px threshold)
    const stage = mount.querySelector('.read-stage');
    let sx = 0, sy = 0;
    stage.addEventListener('touchstart', (e) => {
      sx = e.changedTouches[0].clientX; sy = e.changedTouches[0].clientY;
    }, { passive: true });
    stage.addEventListener('touchend', (e) => {
      const dx = e.changedTouches[0].clientX - sx;
      const dy = e.changedTouches[0].clientY - sy;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) go(dx < 0 ? 1 : -1);
    }, { passive: true });

    runMermaid(mount);
    window.scrollTo(0, 0);

    // announce + move focus to the page region (don't strand focus on body).
    // Skip focus theft while the Sections drawer is the active surface.
    const heading = mount.querySelector('.read-page h1, .read-page .sub-title, .read-page h3, .read-page h4');
    const live = mount.querySelector('.read-live');
    if (live) {
      const secTxt = curSec ? curSec.title + ' — ' : (heading ? heading.textContent.trim() + ' — ' : '');
      live.textContent = secTxt + `Page ${cur + 1} of ${total}`;
    }
    if (!drawerOpen) {
      const page = mount.querySelector('.read-page');
      if (page) page.focus({ preventScroll: true });
    }
  }

  function go(d) {
    const n = cur + d;
    if (n >= 0 && n < total) { dir = d; cur = n; paint(); }
  }
  function jump(n) {
    if (n >= 0 && n < total && n !== cur) { dir = n > cur ? 1 : -1; cur = n; paint(); }
  }

  // Arrow-key paging — self-cleans when Read leaves the DOM; de-duped across re-entry.
  if (activeKeyHandler) document.removeEventListener('keydown', activeKeyHandler);
  activeKeyHandler = (e) => {
    if (!document.querySelector('.read')) { document.removeEventListener('keydown', activeKeyHandler); activeKeyHandler = null; return; }
    const t = (e.target.tagName || '').toLowerCase();
    if (t === 'input' || t === 'textarea' || t === 'select') return;
    if (drawerOpen) return;     // don't page the chapter behind an open Sections drawer (ESC is handled there)
    if (e.key === 'ArrowRight') go(1);
    else if (e.key === 'ArrowLeft') go(-1);
  };
  document.addEventListener('keydown', activeKeyHandler);

  paint();
}

// ── FRAMEWORK EXPLAINER READER ─────────────────────────────────────────────────
// Paginates the 10 static framing pieces — masthead, Part One, CODE outer lens,
// C·O·D·E node-blocks, CODER inner lens, CODER · O/E/R wrappers, #nest, Review,
// Watch, Part Two, Part Three — across Read pages. Mimics the chapter reader's
// chrome: top-row (← Contents · title · Sections ▾), slide-in transitions, swipe,
// arrow keys, page-dot navigation. Same paint-per-page pattern.
async function renderFrameworkExplainer(mount, base) {
  // Defensive load — if the explainer JSON isn't there, fall through to the route-level
  // catch in main.js which shows the "Couldn't load" placeholder rather than crashing.
  let d;
  try { d = await loadJSON(`${base}/course/framework-explainer.json`); }
  catch (e) {
    mount.innerHTML = `<div class="placeholder"><h2>Couldn't load the framework explainer</h2><p>${esc(e.message)}</p></div>`;
    return;
  }

  // Build the page list. Each entry is { title, html }. One piece per page keeps
  // the reading rhythm aligned with the Manual's interleave.
  const pages = [];

  // Page 0 — masthead (the canonical course header). Wrap in an opener-style
  // surface so the Newsreader skin still feels like the rest of Read.
  if (d.masthead) {
    pages.push({
      title: 'Masthead',
      html: `<div class="read-opener">${renderMasthead(d.masthead)}</div>`
    });
  }

  if (d.parts && d.parts.one) pages.push({ title: 'Part One', html: renderPartBanner(d.parts.one) });

  // CODE outer lens — wrapper + telescope.
  if (d.code) pages.push({ title: 'CODE · The Outer Lens', html: renderCodeOuter(d.code) });

  // The four CODE node-blocks (C / O / D / E).
  if (d.code && d.code.nodes) {
    if (d.code.nodes.c) pages.push({ title: 'C · Content',            html: renderNodeBlock('c', d.code.nodes.c) });
    if (d.code.nodes.o) pages.push({ title: 'O · Operations & Martech', html: renderNodeBlock('o', d.code.nodes.o) });
    if (d.code.nodes.d) pages.push({ title: 'D · Design & Data',       html: renderNodeBlock('d', d.code.nodes.d) });
    if (d.code.nodes.e) pages.push({ title: 'E · Engineering',         html: renderNodeBlock('e', d.code.nodes.e) });
  }

  // CODER inner lens — wrapper + telescope + asks + blockquote.
  if (d.coder) pages.push({ title: 'CODER · The Inner Lens', html: renderCoderInner(d.coder) });

  // The three CODER letter intros (O / E / R).
  if (d.coderWrappers) {
    if (d.coderWrappers.o) pages.push({ title: 'CODER · O · Optimization & Quality', html: renderCoderWrapper('o', d.coderWrappers.o) });
    if (d.coderWrappers.e) pages.push({ title: 'CODER · E · External Integrations',  html: renderCoderWrapper('e', d.coderWrappers.e) });
    if (d.coderWrappers.r) pages.push({ title: 'CODER · R · Release Management',     html: renderCoderWrapper('r', d.coderWrappers.r) });
  }

  // The punchline + the two operating tools.
  if (d.nest)   pages.push({ title: 'How it all nests',           html: renderNest(d.nest) });
  if (d.review) pages.push({ title: 'The Executive Review Model', html: renderReview(d.review) });
  if (d.watch)  pages.push({ title: 'Who watches what',           html: renderWatch(d.watch) });

  // Part Two and Part Three banners (the framework hand-offs).
  if (d.parts && d.parts.two)   pages.push({ title: 'Part Two',   html: renderPartBanner(d.parts.two) });
  if (d.parts && d.parts.three) pages.push({ title: 'Part Three', html: renderPartBanner(d.parts.three) });

  // ── Reader state ───────────────────────────────────────────────────────────
  const total = pages.length;
  let cur = 0;
  let dir = 1;
  const SHORT_MAX = 8;
  const useDots = total <= SHORT_MAX;
  const hasSections = total >= 2;
  let drawerOpen = false;

  function dots() {
    let h = '';
    for (let i = 0; i < total; i++) {
      h += `<button type="button" class="pn-dot${i === cur ? ' on' : ''}" data-page="${i}" ` +
        `aria-label="Go to page ${i + 1} of ${total}"${i === cur ? ' aria-current="true"' : ''}></button>`;
    }
    return h;
  }

  function drawerHTML() {
    if (!hasSections) return '';
    const items = pages.map((p, i) =>
      `<li role="none"><button type="button" role="menuitem" class="rd-item${i === cur ? ' on' : ''}" ` +
        `data-page="${i}"${i === cur ? ' aria-current="true"' : ''}>` +
        `<span class="rd-dot" aria-hidden="true"></span>${esc(p.title)}</button></li>`
    ).join('');
    return `<div class="read-drawer" id="readDrawer" hidden>` +
      `<div class="rd-head">Sections</div>` +
      `<ul class="rd-list" role="menu" aria-label="Jump to section">${items}</ul>` +
    `</div>`;
  }

  function paint() {
    const isFirst = cur === 0;
    const isLast = cur === total - 1;
    const slide = dir >= 0 ? 'slide-next' : 'slide-prev';
    const pageTitle = pages[cur].title;
    const pct = total > 1 ? Math.round((cur / (total - 1)) * 100) : 100;

    const topRow =
      `<div class="read-topbar">` +
        `<a class="read-back" href="#/read" aria-label="Back to contents">← Contents</a>` +
        `<span class="read-chtitle">The Framework</span>` +
        (hasSections
          ? `<button type="button" class="read-sections-btn" id="readSectionsBtn" ` +
              `aria-haspopup="true" aria-expanded="${drawerOpen}" aria-controls="readDrawer">Sections ▾</button>`
          : `<span class="read-sections-spacer" aria-hidden="true"></span>`) +
      `</div>`;

    const indicator = useDots
      ? `<div class="pn-dots" role="group" aria-label="Pages">${dots()}</div>`
      : `<div class="pn-progress">` +
          `<div class="pn-bar" aria-hidden="true"><span class="pn-bar-fill" style="width:${pct}%"></span></div>` +
          `<div class="pn-meta">${esc(pageTitle)} · Page ${cur + 1} / ${total}</div>` +
        `</div>`;

    mount.innerHTML =
      `<div class="read read-reader read-framework">` +
        topRow +
        drawerHTML() +
        `<div class="read-stage">` +
          `<div class="read-page ${slide}" tabindex="-1" role="region" aria-label="Reading page">` +
            `<div class="read-flow">${pages[cur].html}</div>` +
          `</div>` +
        `</div>` +
        `<nav class="page-nav${useDots ? '' : ' has-bar'}" aria-label="Page navigation">` +
          `<div class="page-nav-inner">` +
            `<button type="button" class="pn-btn" id="readPrev" ${isFirst ? 'disabled' : ''} aria-label="Previous page">← Prev</button>` +
            indicator +
            `<button type="button" class="pn-btn" id="readNext" ${isLast ? 'disabled' : ''} aria-label="Next page">Next →</button>` +
          `</div>` +
        `</nav>` +
        `<div class="read-live" aria-live="polite" role="status"></div>` +
      `</div>`;

    document.getElementById('readPrev').onclick = () => go(-1);
    document.getElementById('readNext').onclick = () => go(1);
    mount.querySelectorAll('.pn-dot').forEach((b) => {
      b.onclick = () => jump(parseInt(b.dataset.page, 10));
    });

    const secBtn = document.getElementById('readSectionsBtn');
    const drawer = document.getElementById('readDrawer');
    if (secBtn && drawer) {
      const setOpen = (open) => {
        drawerOpen = open;
        drawer.hidden = !open;
        secBtn.setAttribute('aria-expanded', String(open));
        if (open) {
          const first = drawer.querySelector('.rd-item.on') || drawer.querySelector('.rd-item');
          if (first) first.focus();
        }
      };
      secBtn.onclick = () => setOpen(!drawerOpen);
      drawer.querySelectorAll('.rd-item').forEach((b) => {
        b.onclick = () => { drawerOpen = false; jump(parseInt(b.dataset.page, 10)); };
      });
      drawer.onkeydown = (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); secBtn.focus(); }
      };
      if (drawerOpen) setOpen(true);
    }

    // Swipe — same threshold as the chapter reader.
    const stage = mount.querySelector('.read-stage');
    let sx = 0, sy = 0;
    stage.addEventListener('touchstart', (e) => {
      sx = e.changedTouches[0].clientX; sy = e.changedTouches[0].clientY;
    }, { passive: true });
    stage.addEventListener('touchend', (e) => {
      const dx = e.changedTouches[0].clientX - sx;
      const dy = e.changedTouches[0].clientY - sy;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) go(dx < 0 ? 1 : -1);
    }, { passive: true });

    runMermaid(mount);
    window.scrollTo(0, 0);

    const live = mount.querySelector('.read-live');
    if (live) live.textContent = `${pageTitle} — Page ${cur + 1} of ${total}`;
    if (!drawerOpen) {
      const page = mount.querySelector('.read-page');
      if (page) page.focus({ preventScroll: true });
    }
  }

  function go(d) {
    const n = cur + d;
    if (n >= 0 && n < total) { dir = d; cur = n; paint(); }
  }
  function jump(n) {
    if (n >= 0 && n < total && n !== cur) { dir = n > cur ? 1 : -1; cur = n; paint(); }
  }

  if (activeKeyHandler) document.removeEventListener('keydown', activeKeyHandler);
  activeKeyHandler = (e) => {
    if (!document.querySelector('.read')) { document.removeEventListener('keydown', activeKeyHandler); activeKeyHandler = null; return; }
    const t = (e.target.tagName || '').toLowerCase();
    if (t === 'input' || t === 'textarea' || t === 'select') return;
    if (drawerOpen) return;
    if (e.key === 'ArrowRight') go(1);
    else if (e.key === 'ArrowLeft') go(-1);
  };
  document.addEventListener('keydown', activeKeyHandler);

  paint();
}
