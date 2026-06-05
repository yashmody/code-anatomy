// map — the question→answer grid (<div class="map"><div class="map-row"><span class="q">…
// <span class="arrow">→</span><span class="c">…). Used in the Mental Model module.
// q/c are authored course HTML → raw().
import { esc, raw } from '../dom.js';

export function map(block) {
  const title = block.title ? `<div class="arch-title">${esc(block.title)}</div>` : '';
  const rows = (block.rows || []).map((r) =>
    `<div class="map-row"><span class="q">${raw(r.q || '')}</span>` +
    `<span class="arrow">→</span><span class="c">${raw(r.c || '')}</span></div>`
  ).join('');
  return `${title}<div class="map">${rows}</div>`;
}
