// THE single diagram helper — shared by the course `diagram` block (ascii|mermaid|table|versus)
// and the feed `media` diagram (mermaid|ascii|image). Mermaid is never implemented twice.
// table & versus are REAL HTML, never ASCII.
import { esc, raw } from '../util/dom.js';

let mermaidPromise = null;

// Lazy-load Mermaid only when a mermaid-kind item is actually on the page.
export function ensureMermaid() {
  if (window.mermaid) return Promise.resolve(window.mermaid);
  if (mermaidPromise) return mermaidPromise;
  mermaidPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
    s.onload = () => {
      // themeVariables match the live monolith (dark nodes, ochre borders/lines).
      window.mermaid.initialize({
        startOnLoad: false,
        theme: 'base',
        themeVariables: {
          primaryColor: '#0a0a0a', primaryTextColor: '#ffffff', primaryBorderColor: '#FF4900',
          lineColor: '#FF4900', secondaryColor: '#f6f5f1', tertiaryColor: '#f6f5f1',
          fontFamily: 'JetBrains Mono,monospace', fontSize: '13px',
          edgeLabelBackground: '#ffffff', clusterBkg: '#f6f5f1', clusterBorder: '#e6e3dc'
        },
        flowchart: { curve: 'basis', padding: 20 },
        sequence: { actorFontFamily: 'DM Sans,system-ui', noteFontFamily: 'DM Sans,system-ui' }
      });
      resolve(window.mermaid);
    };
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return mermaidPromise;
}

// Process any unrendered <pre class="mermaid"> inside root. Safe to call when there are none.
export async function runMermaid(root) {
  const nodes = (root || document).querySelectorAll('pre.mermaid:not([data-processed="true"])');
  if (!nodes.length) return;
  try {
    const mermaid = await ensureMermaid();
    await mermaid.run({ nodes });
  } catch (e) {
    console.warn('mermaid render failed', e);
  }
}

// renderDiagram(spec) -> HTML string. spec.render selects the form.
export function renderDiagram(spec) {
  const title = spec.title ? `<div class="arch-title">${esc(spec.title)}</div>` : '';
  switch (spec.render) {
    case 'ascii':
      return `<div class="arch-diagram">${title}<pre>${esc(spec.source || spec.ascii || '')}</pre></div>`;
    case 'mermaid':
      return `<div class="arch-diagram">${title}<pre class="mermaid">${esc(spec.source || '')}</pre></div>`;
    case 'table':
      return renderTable(spec, title);
    case 'versus':
      return `${title}${renderVersus(spec)}`;
    case 'image':
      return `<div class="arch-diagram">${title}<img src="${esc(spec.url || '')}" alt="${esc(spec.alt || '')}" loading="lazy"></div>`;
    default:
      return `<div class="arch-diagram"><pre>[unsupported diagram: ${esc(spec.render)}]</pre></div>`;
  }
}

function renderVersus(spec) {
  const cols = (spec.columns || []).map((c) => {
    const tone = c.tone === 'good' ? ' good' : c.tone === 'bad' ? ' bad' : '';
    return `<div class="col${tone}"><div class="vt">${esc(c.label || '')}</div><p>${raw(c.body || '')}</p></div>`;
  }).join('');
  return `<div class="versus">${cols}</div>`;
}

function renderTable(spec, title) {
  const head = (spec.headers || []).length
    ? `<thead><tr>${spec.headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>` : '';
  const body = (spec.rows || []).map(
    (r) => `<tr>${r.map((c) => `<td>${raw(c)}</td>`).join('')}</tr>`
  ).join('');
  return `<div class="arch-diagram">${title}<table class="arch-table">${head}<tbody>${body}</tbody></table></div>`;
}
