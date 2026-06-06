// Fetch JSON from the content-architecture package (the data+contract sibling of app/).
//
// In dev (serving from repo root via Python's http.server), the relative URLs
// like `../content-architecture/course/...` work directly. In production the
// app is mounted at /app/ behind Apache and there is no /content-architecture/
// static alias — so we route every content-architecture URL through the
// FastAPI API which reads from PostgreSQL (or the filesystem for static
// framing files).
import { API_BASE } from './config.js';

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

  const res = await fetch(targetUrl, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${targetUrl}`);
  return res.json();
}
