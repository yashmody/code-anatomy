// code — <pre class="code-ex">, optional .code-label above (monolith pattern).
// `code` is literal source → escaped. (A copy button is layered on after render, like
// the monolith, by the mode composition — kept out of the pure renderer.)
import { esc } from '../dom.js';

export function code(block) {
  const label = block.label ? `<div class="code-label">${esc(block.label)}</div>` : '';
  const lang = block.lang ? ` data-lang="${esc(block.lang)}"` : '';
  return `${label}<pre class="code-ex"${lang}>${esc(block.code || '')}</pre>`;
}
