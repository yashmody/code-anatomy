import { raw } from '../dom.js';
export function lead(block) {
  return `<p class="lead">${raw(block.html || '')}</p>`;
}
