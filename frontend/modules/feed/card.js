// card — a single concept callout. card-top → Syne title → teaser → optional
// linkUrl as a small "Open ↗" link. The ochre left border is the .card--concept
// modifier applied in feed.js. linkUrl is optional. All UGC → escaped.
import { esc } from '../../shared/dom.js';
import { cardTop } from './envelope.js';
export function card(item) {
  const link = item.linkUrl
    ? `<a class="fc-card-link" href="${esc(item.linkUrl)}" target="_blank" rel="noopener noreferrer">Open ↗</a>` : '';
  return cardTop(item) +
    `<div class="card-body"><h3 class="card-title">${esc(item.title || '')}</h3>` +
    `<p class="card-sub">${esc(item.teaser || '')}</p>${link}</div>`;
}
