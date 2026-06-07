// video — short-form. A .video tile FIRST (play button + duration badge + vlabel),
// THEN card-top (pill + kind) → Syne title → hook as sub. If url is empty, the tile
// is the gradient placeholder (no real hosting this pass). All UGC → escaped.
import { esc } from '../../shared/dom.js';
import { cardTop } from './envelope.js';

// durationSec → "M:SS" (e.g. 45 → "0:45", 95 → "1:35").
function fmtDuration(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const m = Math.floor(s / 60);
  const r = String(s % 60).padStart(2, '0');
  return `${m}:${r}`;
}

const PLAY_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>`;

export function video(item) {
  const dur = item.durationSec
    ? `<span class="dur">${esc(fmtDuration(item.durationSec))}</span>` : '';
  // the vlabel reads the hook (short) or falls back to the kind word.
  const vlabel = item.hook
    ? `<span class="vlabel">${esc(String(item.hook).slice(0, 28))}</span>`
    : `<span class="vlabel">Video</span>`;
  // Uploaded video (hosted in the app) → a real player streamed from the unified
  // model. Otherwise the gradient placeholder tile (legacy URL-only posts).
  const tile = item.videoAssetId
    ? `<div class="video"><video class="video-el" controls preload="metadata" playsinline ` +
        `controlslist="nodownload" src="${esc('/media/video/' + item.videoAssetId)}"></video>${dur}</div>`
    : `<div class="video">${vlabel}` +
        `<button class="play" type="button" aria-label="Play video">${PLAY_SVG}</button>${dur}</div>`;
  const hook = item.hook ? `<p class="card-sub">${esc(item.hook)}</p>` : '';
  return tile + cardTop(item) +
    `<div class="card-body"><h3 class="card-title">${esc(item.title || '')}</h3>${hook}</div>`;
}
