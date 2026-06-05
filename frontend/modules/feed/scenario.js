// scenario — a judgement rep. card-top → .scn-prompt (Syne) → options as .scn-opt
// buttons (interactive: tap reveals verdict + reveal, marks correct/wrong) → the
// reveal block. The ochre border is the .card--scenario modifier in feed.js.
// The correct index is marked on each option (data-correct) for the feed.js handler.
// A lettered key (A/B/C…) precedes each option. All UGC → escaped.
import { esc } from '../../shared/dom.js';
import { cardTop } from './envelope.js';

const KEYS = 'ABCDEFGHIJ';

export function scenario(item) {
  const opts = (item.options || []).map((o, i) =>
    `<button class="scn-opt" type="button" data-correct="${i === item.correct ? '1' : '0'}">` +
    `<span class="key" aria-hidden="true">${KEYS[i] || (i + 1)}</span>` +
    `<span class="scn-opt-text">${esc(o)}</span></button>`
  ).join('');
  return cardTop(item) +
    `<div class="card-body">` +
    `<p class="scn-prompt">${esc(item.prompt || '')}</p>` +
    `<div class="scn-opts">${opts}</div>` +
    `<div class="scn-reveal">` +
      `<div class="scn-verdict">${esc(item.verdict || '')}</div>` +
      `<p class="scn-reveal-text">${esc(item.reveal || '')}</p>` +
    `</div></div>`;
}
