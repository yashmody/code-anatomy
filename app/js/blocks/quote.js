import { raw } from '../util/dom.js';
export function quote(block) {
  return `<blockquote>${raw(block.html || '')}</blockquote>`;
}
