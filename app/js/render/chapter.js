// Chapter-level composition helpers shared by Scroll + Read (the scan box is a chapter
// element, not a block, so it lives here rather than in the block registry).
import { raw } from '../util/dom.js';

export function renderScanBox(scan) {
  if (!scan || !scan.length) return '';
  const items = scan.map((s) => `<li>${raw(s)}</li>`).join('');
  return `<div class="scan-box"><div class="scan-box-label">30-second scan</div><ul>${items}</ul></div>`;
}
