import { raw } from '../util/dom.js';
export function prose(block) {
  return `<p>${raw(block.html || '')}</p>`;
}
