// READ mode — the ebook. Same authored content as Scroll, grouped into turnable pages
// by the `page` flag, one chapter per framework letter, with a telescope transition
// generated from `opensInto`. Reuses the exact same block renderers as Scroll.
import { loadFramework, indexFramework } from '../util/framework.js';
import { loadJSON } from '../util/load.js';
import { renderBlock } from '../registry.js';
import { renderScanBox } from '../render/chapter.js';
import { runMermaid } from '../render/diagram.js';
import { esc } from '../util/dom.js';

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

export async function renderRead(mount, base, address, sectionFile) {
  const fw = await loadFramework(base);
  const idx = indexFramework(fw);
  const sec = await loadJSON(`${base}/course/sections/${sectionFile}`);
  const node = idx.byId[address] || {};

  // Flatten blocks in sub-section order; tag the first block of each non-self-headed
  // sub-section with its title so the <h3> rides with that block onto its page.
  const flat = [];
  const subs = (sec.sections || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  for (const sub of subs) {
    (sub.blocks || []).forEach((b, i) => {
      flat.push({ block: b, subTitle: (i === 0 && sub.title && !SELF_HEADED.has(b.type)) ? sub.title : null });
    });
  }

  // Group by `page`.
  const byPage = new Map();
  for (const item of flat) {
    const p = item.block.page || 1;
    if (!byPage.has(p)) byPage.set(p, []);
    byPage.get(p).push(item);
  }
  const pageNums = [...byPage.keys()].sort((a, b) => a - b);

  // Build page HTML: a cover, then one per `page`.
  const pages = [];
  pages.push(
    `<div class="read-cover">` +
      (node.letter ? `<div class="read-cover-mark">${esc(node.letter)}</div>` : '') +
      `<div class="read-cover-ring">${esc((idx.byId[node.ringId] || {}).name || '')}</div>` +
      `<h1 class="read-cover-title">${esc(sec.title)}</h1>` +
      `<div class="read-cover-tag">${esc(sec.tag || '')}</div>` +
      renderScanBox(sec.scan) +
    `</div>`
  );
  for (const p of pageNums) {
    let h = '';
    for (const item of byPage.get(p)) {
      if (item.subTitle) h += `<h3 class="sub-title">${esc(item.subTitle)}</h3>`;
      h += renderBlock(item.block);
    }
    pages.push(`<div class="read-flow">${h}</div>`);
  }

  // End-of-book transition: telescope into a nested ring (opensInto) or next chapter.
  function endHTML() {
    if (node.opensInto) {
      const t = idx.byId[node.opensInto] || {};
      return `<div class="read-telescope"><div class="read-telescope-label">Telescope into</div>` +
        `<div class="read-telescope-target">${esc(t.name || node.opensInto)}</div>` +
        (t.blurb ? `<p>${esc(t.blurb)}</p>` : '') + `</div>`;
    }
    const nx = nextLetter(idx, address);
    return nx
      ? `<div class="read-end"><div class="read-end-label">Next chapter</div><div class="read-end-target">${esc(nx.name)} <span class="read-end-addr">${esc(nx.id)}</span></div></div>`
      : `<div class="read-end"><div class="read-end-label">End of the framework</div></div>`;
  }

  let cur = 0;
  const total = pages.length;

  function paint() {
    const isCover = cur === 0;
    const isLast = cur === total - 1;
    mount.innerHTML =
      `<div class="read">` +
        `<div class="read-stage">${pages[cur]}${isLast ? endHTML() : ''}</div>` +
        `<nav class="read-nav">` +
          `<button class="read-btn" id="readPrev" ${isCover ? 'disabled' : ''} aria-label="Previous page">←</button>` +
          `<span class="read-indicator">${isCover ? 'Cover' : cur + ' / ' + (total - 1)}</span>` +
          `<button class="read-btn" id="readNext" ${isLast ? 'disabled' : ''} aria-label="Next page">→</button>` +
        `</nav>` +
      `</div>`;
    document.getElementById('readPrev').onclick = () => go(-1);
    document.getElementById('readNext').onclick = () => go(1);
    runMermaid(mount);
    window.scrollTo(0, 0);
  }
  function go(d) { const n = cur + d; if (n >= 0 && n < total) { cur = n; paint(); } }

  // Arrow-key paging — self-cleans when Read leaves the DOM; de-duped across re-entry.
  if (activeKeyHandler) document.removeEventListener('keydown', activeKeyHandler);
  activeKeyHandler = (e) => {
    if (!document.querySelector('.read')) { document.removeEventListener('keydown', activeKeyHandler); activeKeyHandler = null; return; }
    const t = (e.target.tagName || '').toLowerCase();
    if (t === 'input' || t === 'textarea' || t === 'select') return;
    if (e.key === 'ArrowRight') go(1);
    else if (e.key === 'ArrowLeft') go(-1);
  };
  document.addEventListener('keydown', activeKeyHandler);

  paint();
}
