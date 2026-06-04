// FEED mode — the social stream. Loads feed.json, shows only `published` items,
// orders by featured pin → recency × engagement (× topic when a filter is active),
// and composes each card as: shared envelope + type body + shared media + footer.
// Its journey is social, NOT the framework.
import { loadJSON } from '../util/load.js';
import { renderFeedBody } from '../registry.js';
import { renderAuthor, renderFooter } from '../feed/envelope.js';
import { renderMedia } from '../feed/media.js';
import { runMermaid } from '../render/diagram.js';
import { esc } from '../util/dom.js';

const TYPE_LABEL = { post: 'Field Note', video: 'Video', list: 'List', card: 'Concept', vocab: 'Vocab', scenario: 'Scenario' };

export async function renderFeed(mount, base) {
  const data = await loadJSON(`${base}/feed/feed.json`);
  const items = (Array.isArray(data) ? data : data.feed || []).filter((it) => it.status === 'published');
  const topics = [...new Set(items.flatMap((it) => it.topics || []))].sort();
  let activeTopic = null;

  // Social score: featured pin, then recency × engagement, plus a topic boost when filtering.
  function scoreOf(it) {
    const ageDays = Math.max(0, (Date.now() - new Date(it.createdAt).getTime()) / 86400000);
    const recency = 1 / (1 + ageDays);                                   // newer → ~1
    const e = it.engagement || {};
    const engagement = (e.upvotes || 0) + 1.5 * (e.comments || 0) + 2 * (e.saves || 0);
    const engNorm = Math.log1p(engagement) / Math.log1p(200);            // ~0–1
    const topicBoost = activeTopic && (it.topics || []).includes(activeTopic) ? 1 : 0;
    return (it.featured ? 100 : 0) + topicBoost * 10 + recency * 0.5 + engNorm * 0.5;
  }

  function cardHTML(it) {
    return `<article class="feed-card" data-type="${esc(it.type)}">` +
      `<div class="fc-type">${esc(TYPE_LABEL[it.type] || it.type)}</div>` +
      renderAuthor(it) +
      `<div class="fc-payload">${renderFeedBody(it)}</div>` +
      renderMedia(it.media) +
      renderFooter(it) +
      `</article>`;
  }

  function paint() {
    const visible = items
      .filter((it) => !activeTopic || (it.topics || []).includes(activeTopic))
      .slice()
      .sort((a, b) => scoreOf(b) - scoreOf(a));

    const chips = `<button class="fc-filter${activeTopic ? '' : ' active'}" type="button" data-topic="">All</button>` +
      topics.map((t) => `<button class="fc-filter${activeTopic === t ? ' active' : ''}" type="button" data-topic="${esc(t)}">#${esc(t)}</button>`).join('');

    mount.innerHTML = `<div class="feed">` +
      `<div class="feed-head"><h1 class="feed-title">The Feed</h1>` +
      `<p class="feed-sub">Field notes from the practice — newest and most useful first. Social, not the syllabus.</p></div>` +
      `<div class="feed-filters" role="tablist" aria-label="Filter by topic">${chips}</div>` +
      (visible.length
        ? `<div class="feed-list">${visible.map(cardHTML).join('')}</div>`
        : `<div class="feed-empty">No published posts${activeTopic ? ' for #' + esc(activeTopic) : ''}.</div>`) +
      `</div>`;
    runMermaid(mount);
  }

  // One delegated click handler, de-duped across re-entry (inert when Feed isn't mounted).
  if (mount._feedClick) mount.removeEventListener('click', mount._feedClick);
  mount._feedClick = function (e) {
    const filter = e.target.closest('.fc-filter');
    if (filter) { activeTopic = filter.dataset.topic || null; paint(); window.scrollTo(0, 0); return; }
    const topic = e.target.closest('.fc-topic');
    if (topic) { activeTopic = topic.dataset.topic || null; paint(); window.scrollTo(0, 0); return; }
    const option = e.target.closest('.fc-option');
    if (option && !option.disabled) { revealScenario(option); return; }
  };
  mount.addEventListener('click', mount._feedClick);

  function revealScenario(option) {
    const sc = option.closest('.fc-scenario');
    if (!sc) return;
    sc.querySelectorAll('.fc-option').forEach((b) => {
      b.disabled = true;
      if (b.dataset.correct === '1') b.classList.add('correct');
    });
    if (option.dataset.correct !== '1') option.classList.add('wrong');
    const reveal = sc.querySelector('.fc-reveal');
    if (reveal) reveal.hidden = false;
  }

  paint();
}
