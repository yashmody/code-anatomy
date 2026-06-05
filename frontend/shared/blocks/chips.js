// chips — .chips > span, matching the monolith. Items are text → escaped.
import { esc } from '../dom.js';

export function chips(block) {
  const items = (block.items || []).map((s) => `<span>${esc(s)}</span>`).join('');
  return `<div class="chips">${items}</div>`;
}
