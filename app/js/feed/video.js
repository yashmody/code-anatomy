// video — short-form. Thumbnail comes through the shared media array.
import { esc } from '../util/dom.js';
export function video(item) {
  const dur = item.durationSec ? `<span class="fc-duration">▶ ${esc(item.durationSec)}s</span>` : '';
  const hook = item.hook ? `<p class="fc-hook">${esc(item.hook)}</p>` : '';
  return `<div class="fc-video-head"><h3 class="fc-title">${esc(item.title || '')}</h3>${dur}</div>${hook}`;
}
