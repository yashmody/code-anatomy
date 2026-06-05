// chapter-open — the drop-cap opener (page 1). The drop letter is a FIELD on this block,
// rendered inside this renderer (no standalone drop renderer). `.drop` is a new on-brand
// component (the monolith has no drop-cap). The body html is re-shelled verbatim.
import { raw, esc } from '../dom.js';

export function chapterOpen(block) {
  const drop = block.drop ? `<span class="drop">${esc(block.drop)}</span>` : '';
  return `<p class="lead chapter-open">${drop}${raw(block.html || '')}</p>`;
}
