// The dispatch registry — renderers[block.type](block). Adding a block type = add a
// renderer file + one entry here. No other code changes. This is the extensibility contract.
import { chapterOpen } from './blocks/chapterOpen.js';
import { lead } from './blocks/lead.js';
import { prose } from './blocks/prose.js';
import { heading } from './blocks/heading.js';
import { tierlist } from './blocks/tierlist.js';
import { diagram } from './blocks/diagram.js';
import { callout } from './blocks/callout.js';
import { code } from './blocks/code.js';
import { quote } from './blocks/quote.js';
import { architectsReview } from './blocks/architectsReview.js';
import { cardgrid } from './blocks/cardgrid.js';
import { chips } from './blocks/chips.js';
import { esc } from './util/dom.js';

export const blockRenderers = {
  'chapter-open': chapterOpen,
  lead,
  prose,
  heading,
  tierlist,
  diagram,
  callout,
  code,
  quote,
  'architects-review': architectsReview,
  cardgrid,
  chips
};

function fallback(block) {
  return `<div class="block-fallback">[no renderer for block type: <code>${esc(block && block.type)}</code>]</div>`;
}

// Dispatch one block to its renderer. Unknown type → visible fallback; a throwing
// renderer is caught so one bad block never takes down the page.
export function renderBlock(block) {
  const fn = blockRenderers[block && block.type] || fallback;
  try {
    return fn(block);
  } catch (e) {
    console.error('renderBlock failed', block, e);
    return fallback(block || {});
  }
}
