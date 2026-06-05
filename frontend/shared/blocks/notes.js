// notes — the arrow-bulleted list (<ul class="notes">) of `<b>term</b> — description`
// items used across the course. Items are authored HTML (re-shell) → raw(), so inline
// <code>/<em>/<b> survive. CSS already lives in the copied design system (ul.notes).
import { raw } from '../dom.js';

export function notes(block) {
  const items = (block.items || []).map((i) => `<li>${raw(i)}</li>`).join('');
  return `<ul class="notes">${items}</ul>`;
}
