// auth-ui.js — the GLOBAL sign-in chrome (app-bar slot + the sign-in popup).
//
// This is presentation only. Every session read / write goes through feed/auth.js
// (which itself goes through feed/store.js — the one place feed data persists). When
// real SSO arrives, the modal's submit handler swaps signInWithEmail() for
// signInWithGoogle(); nothing else here moves.
//
// initAuthUI(onChange) renders the #appAuth slot and wires the popup. `onChange` is
// called after a successful sign-in or sign-out so the shell can re-render the current
// view (e.g. the Feed's compose/flag gates react to the new session).

import { getCurrentSession, signInWithEmail, signOut } from './feed/auth.js';
import { esc } from './util/dom.js';

let _onChange = null;

export function initAuthUI(onChange) {
  _onChange = typeof onChange === 'function' ? onChange : null;
  renderSlot();
}

function firstName(s) {
  return String(s || '').trim().split(/\s+/)[0] || 'there';
}

// ── the app-bar slot: a Sign-in button, or the signed-in identity + Sign out ──────
function renderSlot() {
  const el = document.getElementById('appAuth');
  if (!el) return;
  const s = getCurrentSession();
  if (s) {
    el.innerHTML =
      `<span class="app-user" title="${esc(s.email || '')}">` +
        `<span class="app-user-av" aria-hidden="true">${esc(s.initials || '?')}</span>` +
        `<span class="app-user-name">${esc(firstName(s.name || s.email))}</span>` +
      `</span>` +
      `<button class="app-signout" type="button" id="appSignOut">Sign out</button>`;
    const out = document.getElementById('appSignOut');
    if (out) out.onclick = () => { signOut(); renderSlot(); if (_onChange) _onChange(); };
  } else {
    el.innerHTML = `<button class="app-signin" type="button" id="appSignIn">Sign in</button>`;
    const btn = document.getElementById('appSignIn');
    if (btn) btn.onclick = () => openModal(btn);
  }
}

// ── the popup ─────────────────────────────────────────────────────────────────────
function openModal(trigger) {
  if (document.getElementById('authModalOverlay')) return;   // already open

  const overlay = document.createElement('div');
  overlay.className = 'auth-modal-overlay';
  overlay.id = 'authModalOverlay';
  overlay.innerHTML =
    `<div class="auth-modal" role="dialog" aria-modal="true" aria-labelledby="authModalTitle">` +
      `<button class="auth-modal-close" type="button" aria-label="Close sign in">×</button>` +
      `<div class="auth-modal-eyebrow">DEPT® · Anatomy of Code</div>` +
      `<h2 class="auth-modal-title" id="authModalTitle">Sign in</h2>` +
      `<p class="auth-modal-sub">Single sign-on is coming soon. For now, enter your ` +
        `<strong>@deptagency.com</strong> email to continue.</p>` +
      `<form class="auth-modal-form" novalidate>` +
        `<label class="auth-modal-label" for="authEmail">DEPT® email</label>` +
        `<input class="auth-modal-input" id="authEmail" type="email" inputmode="email" ` +
          `autocomplete="email" spellcheck="false" placeholder="you@deptagency.com" />` +
        `<div class="auth-modal-error" id="authError" role="alert" hidden></div>` +
        `<button class="auth-modal-submit" type="submit">Sign in</button>` +
      `</form>`;
  document.body.appendChild(overlay);

  const input = overlay.querySelector('#authEmail');
  const errEl = overlay.querySelector('#authError');
  const form = overlay.querySelector('.auth-modal-form');

  const close = () => {
    document.removeEventListener('keydown', onKey, true);
    overlay.remove();
    if (trigger && document.contains(trigger)) trigger.focus();
  };
  const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };

  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });
  overlay.querySelector('.auth-modal-close').onclick = close;
  document.addEventListener('keydown', onKey, true);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errEl.hidden = true;
    try {
      await signInWithEmail(input.value);
      close();
      renderSlot();
      if (_onChange) _onChange();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.hidden = false;
      input.focus();
      input.select();
    }
  });

  // focus the field once it is in the DOM
  setTimeout(() => input.focus(), 0);
}
