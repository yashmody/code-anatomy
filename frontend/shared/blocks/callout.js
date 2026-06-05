// callout — .callout.callout-{variant} + .callout-label, matching the monolith.
// why/tip/pitfall wrap their html in a <p> (monolith pattern); before-after carries
// its own .ba-grid markup in html (re-shelled verbatim).
import { raw } from '../dom.js';

const LABEL = {
  why: 'Why This Matters',
  tip: 'Agency Tip',
  pitfall: 'Common Pitfall',
  'before-after': 'Before / After'
};

export function callout(block) {
  const v = block.variant;
  const label = LABEL[v] || 'Note';
  const inner = v === 'before-after' ? raw(block.html || '') : `<p>${raw(block.html || '')}</p>`;
  return `<div class="callout callout-${v}"><span class="callout-label">${label}</span>${inner}</div>`;
}
