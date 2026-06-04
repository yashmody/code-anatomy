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
import { notes } from './blocks/notes.js';
import { map } from './blocks/map.js';
import { esc } from './util/dom.js';

import { post } from './feed/post.js';
import { video } from './feed/video.js';
import { list } from './feed/list.js';
import { card } from './feed/card.js';
import { vocab } from './feed/vocab.js';
import { scenario } from './feed/scenario.js';

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
  chips,
  notes,
  map
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

// Feed dispatch — one renderer per feed type; same extensibility contract as blocks.
// Each renders the type-specific body; the Feed composition wraps the shared envelope + media.
export const feedRenderers = { post, video, list, card, vocab, scenario };

export function renderFeedBody(item) {
  const fn = feedRenderers[item && item.type];
  if (!fn) return `<div class="block-fallback">[no renderer for feed type: <code>${esc(item && item.type)}</code>]</div>`;
  try {
    return fn(item);
  } catch (e) {
    console.error('renderFeedBody failed', item, e);
    return '';
  }
}
