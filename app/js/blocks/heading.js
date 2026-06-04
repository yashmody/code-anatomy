import { raw } from '../util/dom.js';
export function heading(block) {
  return `<h4>${raw(block.html || '')}</h4>`;
}
