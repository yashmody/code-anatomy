// card — a single concept callout. linkUrl is optional.
import { esc } from '../util/dom.js';
export function card(item) {
  const link = item.linkUrl
    ? `<a class="fc-card-link" href="${esc(item.linkUrl)}" target="_blank" rel="noopener noreferrer">Open →</a>` : '';
  return `<div class="fc-concept"><h3 class="fc-title">${esc(item.title || '')}</h3>` +
    `<p class="fc-teaser">${esc(item.teaser || '')}</p>${link}</div>`;
}
