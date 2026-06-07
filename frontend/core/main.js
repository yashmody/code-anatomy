// App shell: hash router across modes (Manual, Read, Feed, Techflix, and the
// role-gated Moderation) + app-bar chrome. All runtime constants live in
// core/config.js; theme state lives in core/theme.js.
//
// Lazy loading: the four heavy mode modules (manual, read, feed, techflix) are
// NOT statically imported — each is imported() the first time the user navigates
// to that mode. _modCache caches the promise so a second visit returns instantly
// without a second network round-trip or script parse.

import { initAuthUI, hasPermission } from './auth-ui.js';
import { initializeAuth } from '../modules/feed/auth.js';
import { QUIZ_URL, SECTION_FILES, CONTENT_BASE } from './config.js';
import { initTheme, toggleTheme } from './theme.js';

// Module-promise cache. Each path is import()-ed exactly once per session.
const _modCache = new Map();
function lazyLoad(path) {
  if (!_modCache.has(path)) _modCache.set(path, import(path));
  return _modCache.get(path);
}

// BASE was the on-disk relative root the old api-client used to derive
// API paths; the api-client now routes through /api/* directly, so this
// only matters as a tag — kept to avoid breaking renderScroll's signature.
const BASE = '';

// Wire the inline-onclick theme button to the theme manager. Kept as a
// global so index.html's <button onclick="toggleAppTheme()"> still works
// without changing the HTML's listener style — Phase 4 nav unification
// can replace this with a managed event.
window.toggleAppTheme = toggleTheme;

const view = document.getElementById('view');

// ---- skeleton loader ----
// Shows a shimmer placeholder that mirrors the real content shape so the
// viewport is never a blank white box while JS/data is in flight.
function showSkeleton(mode) {
  // Helper: one animated line block (width as CSS value, height in px).
  const ln = (w, h = 13) =>
    `<div class="sk-line" style="width:${w};height:${h}px;margin-bottom:${h <= 11 ? 6 : 10}px"></div>`;

  if (mode === 'feed') {
    const card = () => `
      <div class="sk-feed-card">
        <div class="sk-card-hd">
          <div class="sk-avatar sk-line"></div>
          <div class="sk-card-info">
            ${ln('130px', 11)}
            ${ln('90px', 9)}
          </div>
        </div>
        <div class="sk-card-bd">
          ${ln('100%')}${ln('88%')}${ln('62%')}
        </div>
      </div>`;
    view.innerHTML = `<div class="sk-page sk-feed-page">${card()}${card()}${card()}</div>`;
    return;
  }

  if (mode === 'techflix') {
    view.innerHTML = `
      <div class="sk-page sk-tf-page">
        <div class="sk-hero sk-line"></div>
        <div class="sk-tf-grid">
          <div class="sk-thumb sk-line"></div>
          <div class="sk-thumb sk-line"></div>
          <div class="sk-thumb sk-line"></div>
        </div>
      </div>`;
    return;
  }

  // manual / read — two skeleton chapter blocks
  const chapter = (wide) => `
    <div class="sk-chapter-block">
      <div class="sk-ch-head">
        <div class="sk-ch-mark sk-line"></div>
        <div class="sk-ch-meta">
          ${ln('50%', 10)}
          ${ln(wide ? '78%' : '65%', 30)}
        </div>
      </div>
      <div class="sk-ch-body">
        ${ln('96%')}${ln('83%')}${ln('100%')}${ln('71%')}${ln('91%')}${ln('78%')}
      </div>
    </div>`;
  view.innerHTML = `<div class="sk-page">${chapter(false)}${chapter(true)}</div>`;
}

// ---- app-bar chrome: Resources dropdown + global sign-in ----
function initChrome() {
  // Quiz link → the (separately served) quiz app. One constant to repoint (QUIZ_URL in config.js).
  const quiz = document.getElementById('resQuiz');
  if (quiz) quiz.href = QUIZ_URL;

  // Content resource links — Apache aliases /anatomy/ in prod; local dev uses /content/frozen/.
  const resLinks = {
    resFaqs:      `${CONTENT_BASE}/faqs/`,
    resChecklist: `${CONTENT_BASE}/code-coder-checklist.html`,
    resRunbook:   `${CONTENT_BASE}/runbooks/`,
  };
  for (const [id, href] of Object.entries(resLinks)) {
    const el = document.getElementById(id);
    if (el) el.href = href;
  }

  // Resources dropdown — click to toggle; close on outside-click, ESC, or item pick.
  const menu = document.getElementById('resMenu');
  const toggle = document.getElementById('resToggle');
  const dropdown = document.getElementById('resDropdown');
  if (menu && toggle && dropdown) {
    const setOpen = (open) => {
      dropdown.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      menu.classList.toggle('open', open);
    };
    toggle.addEventListener('click', (e) => { e.stopPropagation(); setOpen(dropdown.hidden); });
    dropdown.addEventListener('click', () => setOpen(false));   // pick a link → close
    document.addEventListener('click', (e) => { if (!menu.contains(e.target)) setOpen(false); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !dropdown.hidden) { setOpen(false); toggle.focus(); }
    });
  }

  // Global sign-in — re-render the current view after sign-in/out so gated UI updates.
  initAuthUI(() => route());
}

// ---- router ----
function setActiveTab(mode) {
  document.querySelectorAll('.mode-tab').forEach((a) => {
    a.classList.toggle('active', a.dataset.mode === mode);
  });
}

async function route() {
  let hash = location.hash.replace(/^#\/?/, '') || 'manual';
  // Silent alias: any in-flight #/scroll or #/scroll/... link redirects to manual.
  if (hash === 'scroll' || hash.startsWith('scroll/')) {
    const tail = hash.slice('scroll'.length);
    location.replace('#/manual' + tail);
    return;                       // hashchange will re-enter route()
  }
  const mode = hash.split('/')[0];
  setActiveTab(mode);

  // Show a mode-specific shimmer skeleton immediately — the viewport is never
  // blank while the module JS or JSON data is in flight.
  showSkeleton(mode);

  try {
    if (mode === 'manual') {
      // Lazy: parse manual.js + its ~10 transitive imports only on first visit.
      const { renderScroll } = await lazyLoad('../modules/course/manual.js');
      await renderScroll(view, BASE, SECTION_FILES);
    } else if (mode === 'read') {
      const addr = hash.split('/')[1] || '';             // no address → the Contents library; else the chapter reader
      const file = addr ? addr.replace(/\./g, '-') + '.json' : '';
      const { renderRead } = await lazyLoad('../modules/course/read.js');
      await renderRead(view, BASE, addr, file, SECTION_FILES);
    } else if (mode === 'feed') {
      const { renderFeed } = await lazyLoad('../modules/feed/feed.js');
      await renderFeed(view, BASE);
    } else if (mode === 'techflix') {
      const { renderTechflix } = await lazyLoad('../modules/techflix/techflix.js');
      await renderTechflix(view);
    } else if (mode === 'moderate') {
      // Role-gated. The nav entry is hidden for non-moderators, but a direct
      // #/moderate visit still lands here — show a friendly "not authorised"
      // placeholder rather than fetching (the API would 403 anyway). The lazy
      // import keeps the moderator bundle out of the boot path for everyone else.
      if (!hasPermission('moderate.view')) {
        view.innerHTML =
          '<div class="placeholder"><h2>Not authorised</h2>' +
          '<p>Moderation is restricted to moderators. If you believe you should ' +
          'have access, sign in with a moderator account.</p></div>';
      } else {
        const { renderModerate } = await lazyLoad('../modules/moderate/moderate.js');
        await renderModerate(view);
      }
    } else {
      view.innerHTML = '<div class="placeholder"><h2>Not found</h2></div>';
    }
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="placeholder"><h2>Couldn't load</h2><p>${e.message}</p></div>`;
  }
}

(async () => {
  try {
    await initializeAuth();
  } catch (e) {
    console.warn('Failed to initialize auth', e);
  }
  initTheme();
  initChrome();
  window.addEventListener('hashchange', route);
  route();
})();
