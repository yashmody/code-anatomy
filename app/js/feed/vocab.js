// vocab — a community vocabulary card. term + definition, both UGC → escaped.
import { esc } from '../util/dom.js';
export function vocab(item) {
  return `<div class="fc-vocab"><div class="fc-term">${esc(item.term || '')}</div>` +
    `<div class="fc-def">${esc(item.definition || '')}</div></div>`;
}
