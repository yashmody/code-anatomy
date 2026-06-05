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

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  const label = document.getElementById('themeLabel');
  if (label) label.textContent = t === 'dark' ? 'Light' : 'Dark';
}

export function initTheme() {
  let t = 'light';
  try { t = localStorage.getItem(THEME_KEY) || 'light'; } catch (e) { /* private mode */ }
  applyTheme(t);
}

export function getCurrentTheme() {
  return document.documentElement.dataset.theme || 'light';
}

export function toggleTheme() {
  const next = getCurrentTheme() === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* private mode */ }
  applyTheme(next);
}
