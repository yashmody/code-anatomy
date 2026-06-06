// Single theme manager for the FE shell.
//
// Replaces the three near-identical theme implementations that lived in
// main.js, the resource HTML inline scripts, and the old monolith head.
// Reads/writes localStorage[THEME_KEY] and mirrors the value onto
// document.documentElement.dataset.theme — the CSS variables in
// monolith.css + app.css pivot off the [data-theme] selector.
//
// initTheme() runs on boot. toggleTheme() flips and persists. The label
// inside the toggle button (id="themeLabel") is kept in sync if present.
// All localStorage access is defensively wrapped — private-mode browsers
// throw on access, and the UI must still work without persistence.

import { THEME_KEY } from './config.js';

// Legacy keys the resource islands + quiz used before 4b unified everything
// onto THEME_KEY. All three surfaces (/app, /anatomy, /) are same-origin in
// prod and therefore share localStorage — so on first load after the upgrade
// we adopt whichever legacy value exists rather than dropping the user's
// setting on the floor. Once adopted, the value is persisted under THEME_KEY
// and the legacy keys are never read again.
const LEGACY_THEME_KEYS = ['runbook-theme', 'q0-theme', 'faqs-theme'];

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  const label = document.getElementById('themeLabel');
  if (label) label.textContent = t === 'dark' ? 'Light' : 'Dark';
}

// Resolve the boot theme. Prefer THEME_KEY; if absent, adopt the first legacy
// key present and write it back under THEME_KEY so the migration is one-way.
function resolveTheme() {
  try {
    const current = localStorage.getItem(THEME_KEY);
    if (current === 'dark' || current === 'light') return current;
    for (const k of LEGACY_THEME_KEYS) {
      const v = localStorage.getItem(k);
      if (v === 'dark' || v === 'light') {
        try { localStorage.setItem(THEME_KEY, v); } catch (e) { /* private mode */ }
        return v;
      }
    }
  } catch (e) { /* private mode */ }
  return 'light';
}

export function initTheme() {
  applyTheme(resolveTheme());
}

export function getCurrentTheme() {
  return document.documentElement.dataset.theme || 'light';
}

export function toggleTheme() {
  const next = getCurrentTheme() === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* private mode */ }
  applyTheme(next);
}
