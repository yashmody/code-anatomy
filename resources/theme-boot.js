/* theme-boot.js — unified theme for the resource islands (/anatomy/*).
 *
 * The resource pages (architect-runbook, code-coder-checklist, the FAQs) are
 * plain standalone HTML, NOT ES modules — so this is a classic <script src>,
 * no import/export. It is the non-module sibling of frontend/core/theme.js and
 * MUST agree with it: one storage key, anatomy-app-theme, shared across /app,
 * /anatomy and / because all three are same-origin in production (Apache).
 *
 * Responsibilities:
 *   1. On load, resolve the boot theme (anatomy-app-theme, else adopt a legacy
 *      key once) and apply it to <html data-theme> before paint.
 *   2. Expose window.toggleAppTheme() — flip + persist + refresh every toggle
 *      button's label/icon. Aliased as window.toggleTheme() for the one page
 *      that wires its button via inline onclick="toggleTheme()".
 *   3. Auto-bind any <button id="themeToggle"> click to the same flip.
 *
 * All localStorage access is wrapped: private-mode browsers throw on access and
 * the toggle must still work in-memory for the session.
 */
(function () {
  'use strict';

  var KEY = 'anatomy-app-theme';
  // Order matters only for which legacy setting wins if several exist; in
  // practice a given browser carried at most one of these.
  var LEGACY_KEYS = ['runbook-theme', 'q0-theme', 'faqs-theme'];

  // Canonical Feather-style sun / moon glyphs — identical across every
  // resource page's existing #themeIcon, so swapping innerHTML is safe.
  var MOON = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
  var SUN = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>';

  function read(k) {
    try { return localStorage.getItem(k); } catch (e) { return null; }
  }
  function write(k, v) {
    try { localStorage.setItem(k, v); } catch (e) { /* private mode */ }
  }

  // Prefer the unified key; otherwise adopt the first legacy value present and
  // migrate it under the unified key (one-way).
  function resolve() {
    var current = read(KEY);
    if (current === 'dark' || current === 'light') return current;
    for (var i = 0; i < LEGACY_KEYS.length; i++) {
      var v = read(LEGACY_KEYS[i]);
      if (v === 'dark' || v === 'light') { write(KEY, v); return v; }
    }
    return 'light';
  }

  function refreshControls(t) {
    var dark = t === 'dark';
    // Every resource page uses these ids inside its toggle button.
    var label = document.getElementById('themeLabel');
    if (label) label.textContent = dark ? 'Light Mode' : 'Dark Mode';
    var icon = document.getElementById('themeIcon');
    if (icon) icon.innerHTML = dark ? MOON : SUN;
  }

  function apply(t) {
    document.documentElement.setAttribute('data-theme', t);
    refreshControls(t);
  }

  function current() {
    return document.documentElement.getAttribute('data-theme') === 'dark'
      ? 'dark' : 'light';
  }

  function toggle() {
    var next = current() === 'dark' ? 'light' : 'dark';
    write(KEY, next);
    apply(next);
  }

  // Public API. toggleAppTheme matches the SPA shell + the shared header
  // button; toggleTheme is the legacy inline-onclick name one page still uses.
  window.toggleAppTheme = toggle;
  window.toggleTheme = toggle;

  // Apply as early as this script runs (it is included high in <body>, so the
  // header + body paint with the right theme).
  apply(resolve());

  // Bind the standard toggle button if present and not already wired inline.
  function bind() {
    var btn = document.getElementById('themeToggle');
    if (btn && !btn.getAttribute('onclick')) {
      btn.addEventListener('click', toggle);
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
