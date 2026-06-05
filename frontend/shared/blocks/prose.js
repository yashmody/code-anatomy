import { raw } from '../dom.js';
export function prose(block) {
  return `<p>${raw(block.html || '')}</p>`;
}
