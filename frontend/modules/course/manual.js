// SCROLL mode — sections in framework order, every block rendered linearly.
// This is the renderer-based reproduction of the live monolith page. Built ALONGSIDE
// the monolith (which stays live); it does not replace it.
import { loadFramework, indexFramework, orderIndex } from '../util/framework.js';
import { loadJSON } from '../util/load.js';
import { renderBlock } from '../registry.js';
import { renderScanBox } from '../render/chapter.js';
import { runMermaid } from '../render/diagram.js';
import { esc } from '../util/dom.js';
import {
  renderMasthead, renderPartBanner, renderCodeOuter, renderNodeBlock,
  renderCoderInner, renderCoderWrapper, renderNest, renderReview, renderWatch
} from '../render/explainer.js';

// Block types that render their own heading — don't repeat the sub-section title above them.
const SELF_HEADED = new Set(['chapter-open', 'heading', 'architects-review']);

// CODE-CODER explainer — a hero player at the very top of the Manual. The MP4 ships in
// the repo's /media folder, served from the repo root, so it is one level up from /app.
// The space in the filename is percent-encoded so the URL is valid.
const MANUAL_VIDEO_SRC = '../media/Anatomy%20of%20Code.mp4';
const MANUAL_HERO_DISMISS_KEY = 'anatomy-manual-hero-dismissed';
const MANUAL_HERO =
  `<section class="manual-hero" aria-label="Explainer video">` +
    `<button type="button" class="manual-hero-close" aria-label="Dismiss the hero">×</button>` +
    `<div class="manual-hero-inner">` +
      `<div class="mh-eyebrow">Watch first</div>` +
      `<h2 class="mh-title">The Anatomy of Code — the explainer</h2>` +
      `<p class="mh-sub">A short orientation to the CODE-CODER framework before you read the manual.</p>` +
      `<div class="mh-player">` +
        `<video class="mh-video" controls preload="metadata" playsinline ` +
          `controlslist="nodownload" aria-label="The Anatomy of Code explainer video">` +
          `<source src="${MANUAL_VIDEO_SRC}" type="video/mp4">` +
          `<p class="mh-fallback">Your browser can’t play embedded video. ` +
            `<a href="${MANUAL_VIDEO_SRC}">Download the explainer (MP4)</a>.</p>` +
        `</video>` +
      `</div>` +
    `</div>` +
  `</section>`;

// Read the dismissed flag defensively — in a non-DOM/test context localStorage may not exist.
function heroDismissed() {
  try { return localStorage.getItem(MANUAL_HERO_DISMISS_KEY) === '1'; }
  catch (e) { return false; }
}

export async function renderScroll(mount, base, sectionFiles) {
  const fw = await loadFramework(base);
  const idx = indexFramework(fw);

  // Static framing (masthead + Part banners + CODE/CODER wrappers + node-blocks +
  // #nest + Review + Watch). Lives outside the section JSONs and the schema.
  let expl = null;
  try { expl = await loadJSON(`${base}/course/framework-explainer.json`); }
  catch (e) { console.warn('framework explainer load skipped:', e.message); }

  const sections = [];
  for (const f of sectionFiles) {
    try { sections.push(await loadJSON(`${base}/course/sections/${f}`)); }
    catch (e) { console.warn('section load skipped:', f, e.message); }
  }
  sections.sort((a, b) => orderIndex(idx, a.frameworkAddress) - orderIndex(idx, b.frameworkAddress));

  // The mark glyph for a chapter — the letter for CODE/CODER/Adobe/AI entries; the
  // module token (M00, M01, M01B…) for Anatomy modules. Anything else returns null.
  const markFor = (node) => {
    if (!node) return null;
    if (node.letter) return node.letter;
    if (typeof node.id === 'string' && node.id.startsWith('anatomy.m')) {
      return 'M' + node.id.split('.m')[1].toUpperCase();
    }
    return null;
  };

  let html = '';

  // Masthead first (the canonical course title block) — then the existing video hero
  // sits beneath it. Keeping both: the masthead is the framing the monolith carries,
  // the hero is the orientation video Phase E added. The hero-dismiss toggle still works.
  if (expl && expl.masthead) html += renderMasthead(expl.masthead);
  if (!heroDismissed()) html += MANUAL_HERO;

  // Banner-before-first-chapter-of-a-Part: emit the Part divider lazily, the first
  // time we cross into the section list for that Part. This sidesteps any need to
  // tag framework rings with a "part" — we key off frameworkAddress prefixes.
  const partForAddress = (addr) => {
    if (!addr) return null;
    if (addr.startsWith('adobe.')) return 'two';
    if (addr.startsWith('ai.'))    return 'three';
    return 'one';   // code.*, coder.*, anatomy.*
  };
  let emittedPart = { one: false, two: false, three: false };

  for (let i = 0; i < sections.length; i++) {
    const sec = sections[i];
    const addr = sec.frameworkAddress;
    const node = idx.byId[addr] || {};
    const mark = markFor(node);
    const markClass = mark && mark.length > 1 ? 'chapter-mark compact' : 'chapter-mark';

    // Part banner — lazily on first chapter of a Part. (Part One sits above CODE.)
    const part = partForAddress(addr);
    if (expl && part && !emittedPart[part]) {
      // Nest + Review + Watch close out Part One — emit them BEFORE the Part-Two banner.
      if (part === 'two' && expl.nest)   html += renderNest(expl.nest);
      if (part === 'two' && expl.review) html += renderReview(expl.review);
      if (part === 'two' && expl.watch)  html += renderWatch(expl.watch);
      if (expl.parts && expl.parts[part]) html += renderPartBanner(expl.parts[part]);
      emittedPart[part] = true;
    }

    // Pre-chapter explainer pieces, slotted by frameworkAddress.
    if (expl) {
      if (addr === 'code.c') {
        // The CODE outer-lens wrapper + telescope precedes the FIRST CODE chapter.
        if (expl.code) html += renderCodeOuter(expl.code);
        if (expl.code && expl.code.nodes) html += renderNodeBlock('c', expl.code.nodes.c);
      } else if (addr === 'code.o' && expl.code && expl.code.nodes) {
        html += renderNodeBlock('o', expl.code.nodes.o);
      } else if (addr === 'code.d' && expl.code && expl.code.nodes) {
        html += renderNodeBlock('d', expl.code.nodes.d);
      } else if (addr === 'code.e' && expl.code && expl.code.nodes) {
        html += renderNodeBlock('e', expl.code.nodes.e);
      } else if (addr === 'coder.c') {
        // The CODER inner-lens wrapper + telescope precedes the FIRST CODER chapter.
        if (expl.coder) html += renderCoderInner(expl.coder);
      } else if (addr === 'coder.o' && expl.coderWrappers) {
        html += renderCoderWrapper('o', expl.coderWrappers.o);
      } else if (addr === 'coder.e' && expl.coderWrappers) {
        html += renderCoderWrapper('e', expl.coderWrappers.e);
      } else if (addr === 'coder.r' && expl.coderWrappers) {
        html += renderCoderWrapper('r', expl.coderWrappers.r);
      }
    }

    html += `<article class="chapter" id="${esc(addr)}">`;
    html += `<header class="chapter-head">`;
    if (mark) html += `<div class="${markClass}">${esc(mark)}</div>`;
    html += `<div class="chapter-meta"><div class="chapter-tag">${esc(sec.tag || '')}</div>`;
    html += `<h2 class="chapter-title">${esc(sec.title)}</h2></div></header>`;
    html += renderScanBox(sec.scan);

    const subs = (sec.sections || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
    for (const sub of subs) {
      html += `<section class="sub" id="${esc(sub.id)}">`;
      const blocks = sub.blocks || [];
      // Sub-section title as <h3> (keeps h2→h3→h4 order) unless the first block heads itself.
      if (sub.title && blocks.length && !SELF_HEADED.has(blocks[0].type)) {
        html += `<h3 class="sub-title">${esc(sub.title)}</h3>`;
      }
      for (const block of blocks) {
        let out = renderBlock(block);
        if (block.collapsed) {
          out = `<details class="collapsed-block" open><summary>${esc(sub.title || 'Details')}</summary>${out}</details>`;
        }
        html += out;
      }
      html += `</section>`;
    }

    // Closing ritual — a thin ochre rule + mono kicker pointing at the next chapter,
    // or a quiet "End of the framework" on the final entry. Mirrors the Read mode tail.
    const next = sections[i + 1];
    const thisMark = mark || esc(sec.frameworkAddress);
    const thisTitle = esc(sec.title || '');
    // Collapse "MARK · Title" → just MARK when they match verbatim (avoids cosmetic
    // doubling like "BMAD · BMAD", which happens when framework.json letter === name).
    const thisLabel = thisTitle && esc(thisMark) !== thisTitle
      ? `End of <b>${esc(thisMark)}</b> · ${thisTitle}`
      : `End of <b>${esc(thisMark)}</b>`;
    let kicker;
    if (next) {
      const nextNode = idx.byId[next.frameworkAddress] || {};
      const nextMark = markFor(nextNode);
      const nextTitle = esc(next.title || '');
      const nextLabel = nextMark && esc(nextMark) !== nextTitle
        ? `${esc(nextMark)} · ${nextTitle}`
        : (nextMark ? esc(nextMark) : nextTitle);
      kicker = `<span class="ce-this">${thisLabel}</span>` +
               `<span class="ce-next">Next: ${nextLabel} <span aria-hidden="true">↓</span></span>`;
    } else {
      kicker = `<span class="ce-this">${thisLabel}</span>` +
               `<span class="ce-next">End of the framework</span>`;
    }
    html += `<div class="chapter-end" role="presentation">${kicker}</div>`;
    html += `</article>`;
  }

  // Trailing flush — emit any explainer piece whose boundary chapter never appeared
  // (e.g. SECTION_FILES was curtailed). Nest+Review+Watch close Part One, then any
  // Part banner that didn't fire still gets emitted so the framework explainer is
  // structurally complete even when later Parts are absent.
  if (expl) {
    if (!emittedPart.two) {
      if (expl.nest)   html += renderNest(expl.nest);
      if (expl.review) html += renderReview(expl.review);
      if (expl.watch)  html += renderWatch(expl.watch);
      if (expl.parts && expl.parts.two) html += renderPartBanner(expl.parts.two);
    }
    if (!emittedPart.three && expl.parts && expl.parts.three) {
      html += renderPartBanner(expl.parts.three);
    }
  }

  mount.innerHTML = html;

  // Wire the hero dismiss — persist the flag and pull the section out of the DOM so the
  // mark for code.c sits at the top on the next paint.
  const heroEl = mount.querySelector('.manual-hero');
  const heroClose = heroEl && heroEl.querySelector('.manual-hero-close');
  if (heroClose) {
    heroClose.addEventListener('click', () => {
      try { localStorage.setItem(MANUAL_HERO_DISMISS_KEY, '1'); } catch (e) { /* private mode */ }
      heroEl.remove();
    });
  }

  runMermaid(mount);
}
