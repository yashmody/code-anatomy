// list — checklists / "6 things" posts. card-top → Syne title → optional intro →
// items as a clean list (text left, note muted/mono right). Items are UGC → escaped.
import { esc } from '../../shared/dom.js';
import { cardTop } from './envelope.js';
export function list(item) {
  const intro = item.intro ? `<p class="card-sub fc-intro">${esc(item.intro)}</p>` : '';
  const items = (item.items || []).map((it) =>
    `<li class="fc-li"><span class="fc-li-text">${esc(it.text || '')}</span>` +
    (it.note ? `<span class="fc-li-note">${esc(it.note)}</span>` : '') + `</li>`
  ).join('');
  return cardTop(item) +
    `<div class="card-body"><h3 class="card-title">${esc(item.title || '')}</h3>` +
    `${intro}<ul class="fc-ul">${items}</ul></div>`;
}
