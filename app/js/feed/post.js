// post — the text microblog (Field Note). card-top (pill + kind) → author block
// (avatar gradient + name + role) → optional Syne title → body as a stronger-ink
// card-sub. Body is UGC → escaped. The violet left border is the .card--post
// modifier applied in feed.js.
import { esc } from '../util/dom.js';
import { cardTop, authorBlock } from './envelope.js';
export function post(item) {
  const title = item.title ? `<h3 class="card-title">${esc(item.title)}</h3>` : '';
  return cardTop(item) +
    `<div class="card-body">${authorBlock(item)}${title}` +
    `<p class="card-sub card-sub--strong">${esc(item.body || '')}</p></div>`;
}
