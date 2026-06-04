// tierlist — first-class component (numbered tiers: n · label · note). On-brand new
// component; no monolith equivalent. Data fields are text → escaped.
import { esc } from '../util/dom.js';

export function tierlist(block) {
  const rows = (block.items || []).map((it) =>
    `<div class="tier">` +
      `<span class="tier-n">${esc(it.n || '')}</span>` +
      `<span class="tier-label">${esc(it.label || '')}</span>` +
      (it.note ? `<span class="tier-note">${esc(it.note)}</span>` : '') +
    `</div>`
  ).join('');
  return `<div class="tierlist">${rows}</div>`;
}
