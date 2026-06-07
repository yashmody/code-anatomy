// Fetch JSON from the content-architecture package (the data+contract sibling of app/).
//
// In dev (serving from repo root via Python's http.server), the relative URLs
// like `../content-architecture/course/...` work directly. In production the
// app is mounted at /app/ behind Apache and there is no /content-architecture/
// static alias — so we route every content-architecture URL through the
// FastAPI API which reads from PostgreSQL (or the filesystem for static
// framing files).
//
// Two-layer caching strategy:
//   1. In-process session cache (_cache Map) — survives tab switches within
//      the same SPA session. Navigating Manual→Feed→Manual never re-fetches
//      the 30+ chapter JSONs. Cleared on page reload.
//   2. HTTP browser cache — the backend now sets Cache-Control: max-age=300
//      so a hard-reload still hits the disk cache for 5 min, not the network.
import { API_BASE } from './config.js';

// Module-level session cache. Key = resolved URL; value = parsed JSON object.
// Course content (framework + chapters) is essentially immutable within a
// session — it only changes when an admin re-seeds, which requires a deploy.
const _cache = new Map();

export async function loadJSON(url) {
  let targetUrl = url;
  if (url.includes('/course/framework.json')) {
    targetUrl = `${API_BASE}/api/course/framework`;
  } else if (url.includes('/course/framework-explainer.json')) {
    // Static framing JSON — served from the filesystem by the FastAPI app.
    targetUrl = `${API_BASE}/api/course/framework-explainer`;
  } else if (url.includes('/course/sections/')) {
    const filename = url.substring(url.lastIndexOf('/') + 1);
    targetUrl = `${API_BASE}/api/course/chapters/${filename}`;
  }

  // Return the cached copy immediately — avoids re-fetching on every tab switch.
  if (_cache.has(targetUrl)) return _cache.get(targetUrl);

  // 'default' respects HTTP Cache-Control headers set by the backend (max-age=300).
  // Previously 'no-cache' defeated those headers completely.
  const res = await fetch(targetUrl, { cache: 'default' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${targetUrl}`);
  const data = await res.json();
  _cache.set(targetUrl, data);
  return data;
}
