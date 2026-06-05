// vocab — a community vocabulary card. card-top → term as the Syne card title →
// definition as a card-sub. Light treatment (the reference), not the old dark card.
// term + definition are UGC → escaped.
import { esc } from '../../shared/dom.js';
import { cardTop } from './envelope.js';
export function vocab(item) {
  return cardTop(item) +
    `<div class="card-body"><h3 class="card-title">${esc(item.term || '')}</h3>` +
    `<p class="card-sub">${esc(item.definition || '')}</p></div>`;
}
