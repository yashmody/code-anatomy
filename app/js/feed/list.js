// list — checklists / "6 things" posts. Items are UGC → escaped.
import { esc } from '../util/dom.js';
export function list(item) {
  const intro = item.intro ? `<p class="fc-intro">${esc(item.intro)}</p>` : '';
  const items = (item.items || []).map((it) =>
    `<li class="fc-li"><span class="fc-li-text">${esc(it.text || '')}</span>` +
    (it.note ? `<span class="fc-li-note">${esc(it.note)}</span>` : '') + `</li>`
  ).join('');
  return `<h3 class="fc-title">${esc(item.title || '')}</h3>${intro}<ul class="fc-ul">${items}</ul>`;
}
