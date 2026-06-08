// frontend/core/api.js
// Single front door for every call to the FastAPI backend.
//
// WHY: dev serves the SPA on :8080 and the API on :8000 (cross-origin, same-site),
// so the browser only sends the `aoc_session` cookie when the request sets
// `credentials: 'include'`. Forgetting it silently 401s in dev — which broke
// sign-in entirely once already. Routing every API call through apiFetch makes
// the cookie impossible to forget: credentials are on, in one place, always.
//
// In production API_BASE is '' (same origin behind Apache), so prepending it is a
// no-op and `credentials: 'include'` is harmless. One code path, both environments.
//
// Buildless: plain ES module, relative import, explicit `.js` — no bundler.
import { API_BASE } from './config.js';

// apiFetch(path, opts) — fetch() for the backend API.
//   path : an API path beginning with '/' (e.g. '/auth/me', '/api/feed').
//          API_BASE is prepended (dev: 'http://127.0.0.1:8000'; prod: '').
//   opts : standard fetch init — method / headers / body / cache pass through
//          untouched. `credentials: 'include'` is forced last so it can never be
//          dropped by a caller's options object.
export function apiFetch(path, opts = {}) {
  return fetch(`${API_BASE}${path}`, { ...opts, credentials: 'include' });
}
