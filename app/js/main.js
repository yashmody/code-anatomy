// App shell: hash router across the three modes + per-page theme toggle.
// Scroll is live this pass; Read (step 3) and Feed (step 4) are placeholders for now.
import { renderScroll } from './modes/scroll.js';
import { renderRead } from './modes/read.js';
import { renderFeed } from './modes/feed.js';

const BASE = '../content-architecture';            // app/ reads from its sibling data package
const SECTION_FILES = ['coder-c.json', 'coder-d.json', 'coder-r.json'];   // extracted chapters (Scroll orders them by framework)
const THEME_KEY = 'anatomy-app-theme';             // per-page theme key

const view = document.getElementById('view');

// ---- theme (per-page key, like the monolith family) ----
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  const label = document.getElementById('themeLabel');
  if (label) label.textContent = t === 'dark' ? 'Light' : 'Dark';
}
function initTheme() {
  let t = 'light';
  try { t = localStorage.getItem(THEME_KEY) || 'light'; } catch (e) {}
  applyTheme(t);
}
window.toggleAppTheme = function () {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
  applyTheme(next);
};

// ---- router ----
function setActiveTab(mode) {
  document.querySelectorAll('.mode-tab').forEach((a) => {
    a.classList.toggle('active', a.dataset.mode === mode);
  });
}

async function route() {
  const hash = location.hash.replace(/^#\/?/, '') || 'scroll';
  const mode = hash.split('/')[0];
  setActiveTab(mode);
  view.innerHTML = '<div class="loading">Loading…</div>';
  try {
    if (mode === 'scroll') {
      await renderScroll(view, BASE, SECTION_FILES);
    } else if (mode === 'read') {
      const addr = hash.split('/')[1] || 'coder.d';      // defaults to the first chapter (e.g. #/read/coder.r)
      await renderRead(view, BASE, addr, addr.replace(/\./g, '-') + '.json');
    } else if (mode === 'feed') {
      await renderFeed(view, BASE);
    } else {
      view.innerHTML = '<div class="placeholder"><h2>Not found</h2></div>';
    }
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="placeholder"><h2>Couldn’t load</h2><p>${e.message}</p></div>`;
  }
}

initTheme();
window.addEventListener('hashchange', route);
route();
