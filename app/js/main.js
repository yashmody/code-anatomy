// App shell: hash router across three modes (Manual, Read, Feed) + per-page theme toggle.
import { renderScroll } from './modes/scroll.js';
import { renderRead } from './modes/read.js';
import { renderFeed } from './modes/feed.js';
import { initAuthUI } from './auth-ui.js';

// EDIT HERE → the Quiz is a separate FastAPI server (run: `uvicorn app.main:app`,
// default http://localhost:8000). Repoint this one constant when it moves; the
// Resources → Quiz link reads it on load. The other three resources are static pages.
const QUIZ_URL = 'http://localhost:8000';

const BASE = '../content-architecture';            // app/ reads from its sibling data package
const SECTION_FILES = [   // extracted chapters (Manual orders them by framework, not by this list)
  'code-c.json', 'code-o.json', 'code-d.json', 'code-e.json',
  'coder-c.json', 'coder-o.json', 'coder-d.json', 'coder-e.json', 'coder-r.json',
  'anatomy-m00.json', 'anatomy-m01.json', 'anatomy-m01b.json',
  'anatomy-m02.json', 'anatomy-m02b.json', 'anatomy-m03.json',
  'anatomy-m04.json', 'anatomy-m05.json', 'anatomy-m06.json',
  'anatomy-m07.json', 'anatomy-m08.json', 'anatomy-m09.json', 'anatomy-m10.json',
  'adobe-cm.json', 'adobe-aa.json', 'adobe-cja.json', 'adobe-ajo.json', 'adobe-camp.json',
  'adobe-csc.json', 'adobe-ab.json',
  'ai-bmad.json', 'ai-gov.json'
];
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

// ---- app-bar chrome: Resources dropdown + global sign-in ----
function initChrome() {
  // Quiz link → the (separately served) quiz app. One constant to repoint (QUIZ_URL).
  const quiz = document.getElementById('resQuiz');
  if (quiz) quiz.href = QUIZ_URL;

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
    } else {
      view.innerHTML = '<div class="placeholder"><h2>Not found</h2></div>';
    }
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="placeholder"><h2>Couldn’t load</h2><p>${e.message}</p></div>`;
  }
}

initTheme();
initChrome();
window.addEventListener('hashchange', route);
route();
