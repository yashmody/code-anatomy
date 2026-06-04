// SCROLL mode — sections in framework order, every block rendered linearly.
// This is the renderer-based reproduction of the live monolith page. Built ALONGSIDE
// the monolith (which stays live); it does not replace it.
import { loadFramework, indexFramework, orderIndex } from '../util/framework.js';
import { loadJSON } from '../util/load.js';
import { renderBlock } from '../registry.js';
import { renderScanBox } from '../render/chapter.js';
import { runMermaid } from '../render/diagram.js';
import { esc } from '../util/dom.js';

// Block types that render their own heading — don't repeat the sub-section title above them.
const SELF_HEADED = new Set(['chapter-open', 'heading', 'architects-review']);

export async function renderScroll(mount, base, sectionFiles) {
  const fw = await loadFramework(base);
  const idx = indexFramework(fw);

  const sections = [];
  for (const f of sectionFiles) {
    try { sections.push(await loadJSON(`${base}/course/sections/${f}`)); }
    catch (e) { console.warn('section load skipped:', f, e.message); }
  }
  sections.sort((a, b) => orderIndex(idx, a.frameworkAddress) - orderIndex(idx, b.frameworkAddress));

  let html = '';
  for (const sec of sections) {
    const node = idx.byId[sec.frameworkAddress] || {};
    html += `<article class="chapter" id="${esc(sec.frameworkAddress)}">`;
    html += `<header class="chapter-head">`;
    if (node.letter) html += `<div class="chapter-mark">${esc(node.letter)}</div>`;
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
    html += `</article>`;
  }

  mount.innerHTML = html;
  runMermaid(mount);
}
