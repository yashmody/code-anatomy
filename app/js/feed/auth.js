// feed/auth.js — the Feed sign-in GATE.
//
// HONESTY, PLAINLY:
//   (a) This is a client-side GATE, NOT security. It shapes the UI; it does not
//       protect anything. Browsing the Feed is open and stays open.
//   (b) The @deptagency.com domain check below is trivially bypassable in the
//       browser — anyone can edit this file, the stored session, or the network
//       response and walk straight through. Treat it as a courtesy fence, not a lock.
//   (c) Real enforcement comes with the backend pass: the Google ID token is sent
//       to the server, the server verifies its signature against Google's keys AND
//       checks the email domain there. Only a server-verified session is trustworthy.
//   (d) This module is the SEAM. When the backend arrives, signInWithGoogle() stops
//       decoding the credential locally and instead POSTs the Google credential to
//       the server, which returns the verified session. The UI does not move — it
//       already speaks only to these functions.
//
// Storage discipline: this file NEVER touches localStorage. Every session read /
// write / clear goes through feed/store.js (getSession / setSession / clearSession),
// which is the ONE place feed data persists. Keep it that way.

import { getSession, setSession, clearSession } from './store.js';

// ── CONFIG SLOTS ──────────────────────────────────────────────────────────────
// SLOT: the real OAuth 2.0 Client ID (the user supplies this). Empty = Google
// Identity Services is not configured, so signInWithGoogle() throws a readable
// error and the UI falls back to the dev mock (when DEV_MOCK is true).
export const GOOGLE_CLIENT_ID = '';
// The only domain allowed through the gate. Exact match, case-insensitive.
export const ALLOWED_DOMAIN = 'deptagency.com';
// Dev flag — set false for a production build. Enables the mock sign-in so the UI
// is testable WITHOUT a real client ID.
export const DEV_MOCK = true;
// The Google Identity Services client library (lazy-loaded on first sign-in only).
const GIS_SRC = 'https://accounts.google.com/gsi/client';
// How long to wait for GIS to become ready before giving up (ms).
const GIS_TIMEOUT = 8000;

// ── PURE: the domain gate ───────────────────────────────────────────────────────
// true iff `email` is a non-empty string whose domain (everything after the LAST
// '@', lower-cased) equals ALLOWED_DOMAIN exactly. Rejects lookalikes outright:
//   deptagency.com.evil.com  → domain is "deptagency.com.evil.com" ≠ "deptagency.com"
//   x@notdeptagency.com      → domain is "notdeptagency.com"        ≠ "deptagency.com"
// Also rejects empty / non-string / no-'@' / trailing-'@' (empty local part or domain).
export function isAllowedEmail(email) {
  if (typeof email !== 'string') return false;
  const at = email.lastIndexOf('@');
  if (at <= 0 || at === email.length - 1) return false; // no '@', or empty local/domain part
  const domain = email.slice(at + 1).toLowerCase();
  return domain === ALLOWED_DOMAIN;
}

// ── PURE: read the GIS credential JWT ────────────────────────────────────────────
// Splits a JWT and base64url-decodes the PAYLOAD segment only. This does NOT verify
// the signature — signature verification is the server's job (see header note (c)).
// We read the payload purely to populate the client UI (email / name / picture).
// Returns the claims object, or null on any malformed input.
export function decodeJwtPayload(jwt) {
  if (typeof jwt !== 'string') return null;
  const parts = jwt.split('.');
  if (parts.length !== 3) return null;
  try {
    // base64url → base64, then decode. atob handles the rest; we UTF-8-decode so
    // names with non-ASCII characters survive.
    let b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    while (b64.length % 4) b64 += '=';
    const bin = atob(b64);
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    const json = new TextDecoder('utf-8').decode(bytes);
    const claims = JSON.parse(json);
    return (claims && typeof claims === 'object') ? claims : null;
  } catch (e) {
    return null;
  }
}

// ── PURE: build our session shape from Google claims ─────────────────────────────
// { userId, email, name, initials, picture? }. See the per-field rules inline.
export function sessionFromClaims(claims) {
  const c = claims || {};
  const email = typeof c.email === 'string' ? c.email : '';
  const localPart = email.includes('@') ? email.slice(0, email.indexOf('@')) : email;
  const name = (typeof c.name === 'string' && c.name.trim()) ? c.name.trim() : localPart;
  // userId: a stable-ish client id — local-part if we have an email, else the sub claim.
  const userId = 'u.' + (localPart || (typeof c.sub === 'string' ? c.sub : 'unknown'));
  const session = { userId, email, name, initials: initialsFor(name, email) };
  if (typeof c.picture === 'string' && c.picture) session.picture = c.picture;
  return session;
}

// Initials: first letters of up to 2 name words, uppercased. Fallback: first 2
// characters of the email (local part). Always returns 1–2 uppercase characters.
function initialsFor(name, email) {
  const words = String(name || '').trim().split(/\s+/).filter(Boolean);
  if (words.length) {
    return words.slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  }
  const seed = String(email || '').replace(/@.*$/, '');
  return (seed.slice(0, 2) || '?').toUpperCase();
}

// ── GIS lazy loader ─────────────────────────────────────────────────────────────
// Inject the Google Identity Services <script> exactly once and resolve when
// google.accounts.id is ready. Idempotent: repeat calls share the same promise.
// NOT called on module import — only when a real Google sign-in is attempted.
let _gisPromise = null;
export function loadGis() {
  if (_gisPromise) return _gisPromise;
  _gisPromise = new Promise((resolve, reject) => {
    // Already present (e.g. the script tag survived a re-render)?
    if (window.google && window.google.accounts && window.google.accounts.id) {
      resolve(window.google.accounts.id);
      return;
    }
    const ready = () => window.google && window.google.accounts && window.google.accounts.id;
    const fail = (msg) => { _gisPromise = null; reject(new Error(msg)); };

    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      fail('Google sign-in did not load in time. Check your connection and try again.');
    }, GIS_TIMEOUT);

    const finish = () => {
      if (settled) return;
      // GIS sets google.accounts.id slightly after onload in some builds — poll briefly.
      const t0 = Date.now();
      (function poll() {
        if (settled) return;
        if (ready()) { settled = true; clearTimeout(timer); resolve(window.google.accounts.id); return; }
        if (Date.now() - t0 > 2000) { settled = true; clearTimeout(timer); fail('Google sign-in loaded but did not initialise.'); return; }
        setTimeout(poll, 50);
      })();
    };

    let script = document.querySelector('script[data-gis]');
    if (!script) {
      script = document.createElement('script');
      script.src = GIS_SRC;
      script.async = true;
      script.defer = true;
      script.setAttribute('data-gis', '1');
      script.addEventListener('load', finish);
      script.addEventListener('error', () => { clearTimeout(timer); fail('Could not load Google sign-in.'); });
      document.head.appendChild(script);
    } else {
      // Script tag exists already; just wait for readiness.
      finish();
    }
  });
  return _gisPromise;
}

// ── Real Google sign-in ──────────────────────────────────────────────────────────
// Resolves to our session on success; rejects with a readable Error otherwise.
// `container` (optional) is an element to render the GIS button into; if omitted we
// fall back to the One Tap prompt(). Either way the credential callback is the path
// that resolves this promise.
export function signInWithGoogle(container) {
  return new Promise((resolve, reject) => {
    if (!GOOGLE_CLIENT_ID) {
      reject(new Error('Google sign-in is not configured yet — set GOOGLE_CLIENT_ID in auth.js.'));
      return;
    }
    let settled = false;
    const done = (fn, arg) => { if (settled) return; settled = true; fn(arg); };

    loadGis().then((id) => {
      id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => {
          const claims = decodeJwtPayload(response && response.credential);
          if (!claims || !claims.email) {
            done(reject, new Error('Google did not return an email. Please try again.'));
            return;
          }
          if (!isAllowedEmail(claims.email)) {
            // GATE (not security): reject, and do NOT set a session.
            done(reject, new Error(
              `Only @${ALLOWED_DOMAIN} accounts may sign in. (${claims.email} was rejected.)`
            ));
            return;
          }
          const session = sessionFromClaims(claims);
          setSession(session);            // → store.js → localStorage. Never here.
          done(resolve, session);
        }
      });
      // Prefer a rendered button when we have a container; else the One Tap prompt.
      if (container) {
        id.renderButton(container, { theme: 'outline', size: 'large', text: 'signin_with', shape: 'pill' });
      } else {
        id.prompt();
      }
    }).catch((err) => done(reject, err));
  });
}

// ── Email sign-in (pre-SSO interim) ───────────────────────────────────────────────
// The UI collects a typed @deptagency.com email and calls this. It is the SAME GATE
// as Google sign-in (header note (a)/(b)): a client-side courtesy fence, not security.
// When real SSO lands, the sign-in UI swaps this call for signInWithGoogle(); the
// session shape and storage discipline (setSession via store.js) do not change.
// Validates the domain, derives the session from the email, persists it, and returns it.
// Throws a readable Error on a missing / malformed / wrong-domain address.
export function signInWithEmail(email) {
  const value = (typeof email === 'string' ? email : '').trim();
  if (!value) throw new Error('Enter your DEPT® email to sign in.');
  if (!isAllowedEmail(value)) {
    throw new Error(`Enter a valid @${ALLOWED_DOMAIN} email address.`);
  }
  const session = sessionFromClaims({ email: value });
  setSession(session);                    // → store.js → localStorage. Never here.
  return session;
}

// ── DEV mock sign-in ──────────────────────────────────────────────────────────────
// A clearly-fake @deptagency.com session so the UI is testable without a client ID.
// Throws if DEV_MOCK is off (so it cannot leak into a production build by accident).
export function signInDevMock() {
  if (!DEV_MOCK) throw new Error('Dev sign-in is disabled (DEV_MOCK is false).');
  const session = { userId: 'u.dev', email: 'dev@deptagency.com', name: 'Dev User', initials: 'DU' };
  setSession(session);                    // → store.js. Never localStorage here.
  return session;
}

// ── session pass-throughs (the UI imports auth, not store, for session reads) ─────
export function signOut() {
  clearSession();
}
export function getCurrentSession() {
  return getSession();
}
export function isSignedIn() {
  return !!getSession();
}

// The gating helper Steps 5 (compose) and 6 (flag) call before a privileged action.
// Returns the session, or throws — callers show the message and prompt sign-in.
export function requireSession() {
  const s = getSession();
  if (!s) throw new Error('Please sign in with your @deptagency.com account to do that.');
  return s;
}
