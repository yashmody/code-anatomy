// The shared media renderer — hangs on the envelope, works for EVERY feed type.
// image  -> <img> with mandatory alt
// diagram -> the SAME renderDiagram helper the course `diagram` block uses (no second impl)
import { esc } from '../../shared/dom.js';
import { renderDiagram } from '../../shared/render/diagram.js';

export function renderMedia(media) {
  if (!media || !media.length) return '';
  const out = media.map((m) => {
    if (m.kind === 'image') {
      if (!m.url) return '';                      // empty url (placeholder data) → render nothing, not a broken img
      if (m.alt == null) console.warn('media image missing alt:', m);  // alt required; never silently fabricated
      const alt = esc(m.alt || '');
      const dims = (m.width && m.height) ? ` width="${esc(m.width)}" height="${esc(m.height)}"` : '';
      const cap = m.caption ? `<figcaption class="fc-cap">${esc(m.caption)}</figcaption>` : '';
      return `<figure class="fc-media fc-media-img"><img src="${esc(m.url)}" alt="${alt}" loading="lazy"${dims}>${cap}</figure>`;
    }
    if (m.kind === 'diagram') {
      return `<div class="fc-media fc-media-diagram">${renderDiagram({ render: m.render, source: m.source, url: m.url, alt: m.alt })}</div>`;
    }
    return '';
  }).join('');
  return out;
}
