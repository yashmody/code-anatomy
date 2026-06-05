import { raw } from '../dom.js';
export function quote(block) {
  return `<blockquote>${raw(block.html || '')}</blockquote>`;
}
