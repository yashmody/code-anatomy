// architects-review — .arch-review > .arch-label + ul>li, matching the monolith.
import { esc, raw } from '../util/dom.js';

export function architectsReview(block) {
  const label = block.label || "Architect's Review";
  const items = (block.items || []).map((it) => `<li>${raw(it)}</li>`).join('');
  return `<div class="arch-review"><div class="arch-label">${esc(label)}</div><ul>${items}</ul></div>`;
}
