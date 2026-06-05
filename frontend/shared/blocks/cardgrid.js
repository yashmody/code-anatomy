// cardgrid — .cards > .cell (.ct eyebrow + h5 title + p body), matching the monolith.
// The monolith .cards uses auto-fit columns, so `columns` is advisory (auto-fit lays
// 3 cards in 3 columns on desktop) — kept identical to the monolith by not overriding it.
import { esc, raw } from '../dom.js';

export function cardgrid(block) {
  const cells = (block.cards || []).map((c) =>
    `<div class="cell">` +
      (c.eyebrow ? `<div class="ct">${esc(c.eyebrow)}</div>` : '') +
      `<h5>${raw(c.title || '')}</h5>` +
      (c.body ? `<p>${raw(c.body)}</p>` : '') +
    `</div>`
  ).join('');
  return `<div class="cards">${cells}</div>`;
}
