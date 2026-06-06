// feed/auth.js — the Feed sign-in GATE.
// Upgraded to connect directly to the FastAPI PostgreSQL backend.

import { API_BASE } from '../../core/config.js';

export const GOOGLE_CLIENT_ID = '';
export const ALLOWED_DOMAIN = 'deptagency.com';
export const DEV_MOCK = true;

let activeSession = null;

export function isAllowedEmail(email) {
  if (typeof email !== 'string') return false;
  const at = email.lastIndexOf('@');
  if (at <= 0 || at === email.length - 1) return false;
  const domain = email.slice(at + 1).toLowerCase();
  return domain === ALLOWED_DOMAIN;
}

export function decodeJwtPayload(jwt) {
  return null;
}

export function sessionFromClaims(claims) {
  return claims;
}

export function loadGis() {
  return Promise.resolve(null);
}

// Global initialization function to fetch current session on startup
export async function initializeAuth() {
  try {
    const res = await fetch(`${API_BASE}/auth/me`);
    if (res.ok) {
      activeSession = await res.json();
    } else {
      activeSession = null;
    }
  } catch (e) {
    activeSession = null;
  }
  return activeSession;
}

export function signInWithGoogle(container) {
  // Single-origin redirection to Google Auth endpoint
  window.location.href = `${API_BASE}/auth/google`;
  return new Promise(() => {}); // Never resolves as page redirects
}

export async function signInWithEmail(email) {
  const value = (typeof email === 'string' ? email : '').trim();
  if (!value) throw new Error('Enter your DEPT® email to sign in.');
  if (!isAllowedEmail(value)) {
    throw new Error(`Enter a valid @${ALLOWED_DOMAIN} email address.`);
  }

  const formData = new URLSearchParams();
  formData.append('email', value);

  const res = await fetch(`${API_BASE}/login/dev`, {
    method: 'POST',
    body: formData,
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    }
  });

  if (!res.ok) {
    throw new Error('Login failed on server.');
  }

  // Refresh dynamic session info
  await initializeAuth();
  return activeSession;
}

export async function signInDevMock() {
  return signInWithEmail('dev@deptagency.com');
}

export async function signOut() {
  activeSession = null;
  try {
    await fetch(`${API_BASE}/logout`);
  } catch (e) {
    console.warn('Signout request failed', e);
  }
  // Reload the page to clear state
  window.location.reload();
}

export function getCurrentSession() {
  return activeSession;
}

export function isSignedIn() {
  return !!activeSession;
}

export function requireSession() {
  if (!activeSession) {
    throw new Error('Please sign in with your @deptagency.com account to do that.');
  }
  return activeSession;
}
