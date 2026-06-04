import { raw } from '../util/dom.js';
// Sub-section heading. Emits <h3 class="sub-title"> (Syne, 24 px, see app.css) — NOT <h4>,
// which monolith.css styles as a tiny mono-uppercase eyebrow chip. This block is the
// section title; it must outrank the 17 px ambient prose and the 21 px cardgrid <h5>.
export function heading(block) {
  return `<h3 class="sub-title">${raw(block.html || '')}</h3>`;
}
