// post — the text microblog (Field Note). Body is UGC → escaped.
import { esc } from '../util/dom.js';
export function post(item) {
  const title = item.title ? `<h3 class="fc-title">${esc(item.title)}</h3>` : '';
  return `${title}<p class="fc-body">${esc(item.body || '')}</p>`;
}
