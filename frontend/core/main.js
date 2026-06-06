// App shell: hash router across three modes (Manual, Read, Feed) +
// app-bar chrome. All runtime constants live in core/config.js; theme
// state lives in core/theme.js.

import { renderScroll } from '../modules/course/manual.js';
import { renderRead } from '../modules/course/read.js';
import { renderFeed } from '../modules/feed/feed.js';
import { initAuthUI, hasPermission } from './auth-ui.js';
import { initializeAuth } from '../modules/feed/auth.js';
import { QUIZ_URL, SECTION_FILES, CONTENT_BASE } from './config.js';
import { initTheme, toggleTheme } from './theme.js';

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

// ---- app-bar chrome: Resources dropdown + global sign-in ----
function initChrome() {
  // Quiz link → the (separately served) quiz app. One constant to repoint (QUIZ_URL in config.js).
  const quiz = document.getElementById('resQuiz');
  if (quiz) quiz.href = QUIZ_URL;

  // Content resource links — Apache aliases /anatomy/ in prod; local dev uses /content/frozen/.
  const resLinks = {
    resFaqs:      `${CONTENT_BASE}/faqs/aem-banking-faq.html`,
    resChecklist: `${CONTENT_BASE}/code-coder-checklist.html`,
    resRunbook:   `${CONTENT_BASE}/architect-runbook.html`,
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
  view.innerHTML = '<div class="loading">Loading…</div>';
  try {
    if (mode === 'manual') {
      await renderScroll(view, BASE, SECTION_FILES);
    } else if (mode === 'read') {
      const addr = hash.split('/')[1] || '';             // no address → the Contents library; else the chapter reader
      const file = addr ? addr.replace(/\./g, '-') + '.json' : '';
      await renderRead(view, BASE, addr, file, SECTION_FILES);
    } else if (mode === 'feed') {
      await renderFeed(view, BASE);
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
        const { renderModerate } = await import('../modules/moderate/moderate.js');
        await renderModerate(view);
      }
    } else {
      view.innerHTML = '<div class="placeholder"><h2>Not found</h2></div>';
    }
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="placeholder"><h2>Couldn’t load</h2><p>${e.message}</p></div>`;
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
