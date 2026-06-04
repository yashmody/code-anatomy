// scenario — a judgement rep. Interactive: tap an option, the verdict + reveal show.
// The correct index is marked on the option (data-correct) for the click handler in feed.js.
import { esc } from '../util/dom.js';
export function scenario(item) {
  const opts = (item.options || []).map((o, i) =>
    `<button class="fc-option" type="button" data-correct="${i === item.correct ? '1' : '0'}">${esc(o)}</button>`
  ).join('');
  return `<div class="fc-scenario">` +
    `<p class="fc-prompt">${esc(item.prompt || '')}</p>` +
    `<div class="fc-options">${opts}</div>` +
    `<div class="fc-reveal" hidden>` +
      `<div class="fc-verdict">${esc(item.verdict || '')}</div>` +
      `<p class="fc-reveal-text">${esc(item.reveal || '')}</p>` +
    `</div></div>`;
}
