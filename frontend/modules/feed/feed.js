// FEED mode — the social stream, store-driven (Step 3 + visual-parity re-skin).
// All feed data comes from ../feed/store.js (the seam). This file NEVER touches
// localStorage; storage lives behind the store. The card composition reuses the
// shared envelope (pill + kind + author + foot bridge) + type body + media.
//
// Browse/filter: sort is recency DESC (engagement, then id, as tiebreaks — owned by
// the store). Readers compose filters: CATEGORY chips (framework letters + an
// "Other / Uncategorised" bucket), TAG chips (topics[]), and an optional group-by-day.
// The three dimensions compose with AND; within a dimension, OR.
//
// The sign-in/out UI (Step 4) lives in the feed head; session reads go through auth.js
// (which speaks to the store), so this file still never touches localStorage. The compose
// (Step 5) and flag (Step 6) controls gate on that same session.
//
// FLAG STATE IS CLIENT-SIDE ONLY this pass. flagPost() writes the per-browser
// `feedStore.flags` overlay inside store.js — it does NOT propagate to other users, and
// "Marked for deletion" does not actually delete anything. Shared, persistent, cross-user
// flagging and real moderator deletion are the backend pass. The flag-to-mark threshold is
// store.js's FLAG_THRESHOLD (default 1) — referenced, never duplicated, so a single
// confirm flips a post to 'flagged'. We only build the UI that CALLS flagPost.
import { listPosts, getAllTopics, getAllCategories, configureFeedStore, flagPost } from '../feed/store.js';
import {
  getCurrentSession, isSignedIn, signInWithGoogle, signInDevMock, signOut,
  GOOGLE_CLIENT_ID, DEV_MOCK
} from '../feed/auth.js';
import { renderFeedBody } from '../registry.js';
import { renderFooter, topicChips, flaggedBadge, flagConfirmHTML } from '../feed/envelope.js';
import { renderMedia } from '../feed/media.js';
import { runMermaid } from '../render/diagram.js';
import { esc } from '../util/dom.js';
import { openComposer } from '../feed/composer.js';

// Card modifiers per type, applied alongside the base .card class. The visual
// language: post → violet field-note border, scenario → ochre judgement border,
// card → ochre concept border. Other types get the plain card.
const CARD_MOD = { post: 'card--post', scenario: 'card--scenario', card: 'card--concept' };

// ── PROGRESS RIBBON (decorative) ──────────────────────────────────────────────
// Placeholder — the Feed has no real framework-progress model this pass (it's
// socially ordered, not a syllabus). A user-progress model / backend supplies real
// values later. This ribbon is decorative for now; do NOT read it as authoritative.
const FEED_PROGRESS = { pct: 38, now: 'Deployment' };

// Deterministic date formatting — fixed 'en-GB' locale so output never drifts with
// the host environment. "DD Mon YYYY", e.g. "27 May 2026".
const DATE_FMT = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });

// Day key (YYYY-MM-DD, UTC) so cards group into the same day deterministically.
function dayKey(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return 'unknown';
  return d.toISOString().slice(0, 10);
}

// Human label for a day divider: Today / Yesterday / "DD Mon YYYY", relative to now.
function dayLabel(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return 'Undated';
  const today = dayKey(new Date().toISOString());
  const yest = dayKey(new Date(Date.now() - 86400000).toISOString());
  const k = dayKey(iso);
  if (k === today) return 'Today';
  if (k === yest) return 'Yesterday';
  return DATE_FMT.format(d);
}

export async function renderFeed(mount, base) {
  configureFeedStore(base);

  // Filter state lives in the closure.
  const selectedCategories = new Set();
  const selectedTags = new Set();
  let groupByDay = false;
  // Flagged posts SHOW by default (per spec — "marked for deletion" is a visible state,
  // not a removal). "Hide flagged" ON passes includeFlagged:false to listPosts.
  let hideFlagged = false;

  // ── KEYBOARD-FOCUS RESTORE ACROSS REPAINTS (a11y) ─────────────────────────────
  // paint() rebuilds the whole feed via innerHTML, so every repaint (filter toggle,
  // group/clear/hide, auth, post, flag) would otherwise drop keyboard focus to <body>.
  // Two closure hints fix that, consumed once per paint:
  //   • nextFocus  — an EXPLICIT target a handler sets when the focused control is about
  //                  to transform/vanish by design (sign-in→sign-out, flag→flagged card).
  //                  A selector string, queried inside the freshly-painted mount. Wins.
  //   • pendingFocus — the AUTOMATIC fallback: a stable selector for whatever the user
  //                  was on, captured just before innerHTML is replaced.
  let pendingFocus = null;
  let nextFocus = null;

  // A stable selector for `el` from its most stable attribute, in priority order, so the
  // same logical control can be re-found in the rebuilt DOM. null when nothing stable fits.
  function stableSelector(el) {
    if (!el || el === mount || !mount.contains(el)) return null;
    if (el.dataset) {
      if (el.dataset.cat != null) return `[data-cat="${CSS.escape(el.dataset.cat)}"]`;
      if (el.dataset.tag != null) return `[data-tag="${CSS.escape(el.dataset.tag)}"]`;
      if (el.dataset.flag != null) return `[data-flag="${CSS.escape(el.dataset.flag)}"]`;
      if (el.dataset.newpost != null) return '[data-newpost]';
    }
    for (const cls of ['fc-group', 'fc-clear', 'fc-hideflagged',
      'auth-google', 'auth-dev', 'auth-signout']) {
      if (el.classList && el.classList.contains(cls)) return `.${cls}`;
    }
    return null;
  }

  // Filter sources (built from framework.json + visible posts; fetched once).
  const [categories, topics] = await Promise.all([getAllCategories(), getAllTopics()]);

  // One card. The base .card plus a per-type modifier (violet/ochre borders). The
  // type body emits its own card-top (pill + kind) + card-body; we append the topic
  // chips, the shared media, and the foot (engagement + the Read bridge + flag control).
  // idx drives a small rise-in stagger via animation-delay (CSS only — never affects
  // ordering). A flagged post (status === 'flagged') gets the `card--flagged` treatment
  // (dimmed + dashed-ochre border) plus a top badge whose TEXT carries the state — the
  // body stays readable (pending review, not removed). The foot's flag control is gated
  // on the session (signed-in only) and replaced by a "Flagged · Pending" indicator once
  // flagged, so the same browser can't re-flag.
  function cardHTML(it, idx) {
    const mod = CARD_MOD[it.type] ? ` ${CARD_MOD[it.type]}` : '';
    const flagged = it.status === 'flagged' ? ' card--flagged' : '';
    const delay = `style="animation-delay:${Math.min(idx, 8) * 45}ms"`;
    // data-id + tabindex="-1" let the flag-confirm transform case (FIX 1) move focus to
    // the exact card whose Flag button just vanished — the article can receive
    // programmatic focus without ever entering the tab order.
    return `<article class="card${mod}${flagged}" data-type="${esc(it.type)}" ` +
      `data-id="${esc(it.id)}" tabindex="-1" ${delay}>` +
      flaggedBadge(it) +
      renderFeedBody(it) +
      topicChips(it) +
      renderMedia(it.media) +
      renderFooter(it, isSignedIn()) +
      `</article>`;
  }

  // The card list, optionally broken by date dividers when groupByDay is on.
  function listHTML(posts) {
    if (!posts.length) {
      return `<div class="feed-empty">No posts match these filters.</div>`;
    }
    if (!groupByDay) {
      return `<div class="feed-list">${posts.map((it, i) => cardHTML(it, i)).join('')}</div>`;
    }
    let out = '';
    let lastDay = null;
    posts.forEach((it, i) => {
      const k = dayKey(it.createdAt);
      if (k !== lastDay) {
        out += `<div class="feed-divider"><span>${esc(dayLabel(it.createdAt))}</span></div>`;
        lastDay = k;
      }
      out += cardHTML(it, i);
    });
    return `<div class="feed-list">${out}</div>`;
  }

  // Category chips, CODE row + CODER row visually grouped, "Other" chip at the end.
  function categoryBar() {
    const byRing = new Map();        // ring name → chip[]
    let other = null;
    for (const c of categories) {
      if (c.id === 'other') { other = c; continue; }
      if (!byRing.has(c.ring)) byRing.set(c.ring, []);
      byRing.get(c.ring).push(c);
    }
    const chip = (c) =>
      `<button class="fc-cat${selectedCategories.has(c.id) ? ' active' : ''}" type="button" ` +
      `data-cat="${esc(c.id)}" aria-pressed="${selectedCategories.has(c.id)}">` +
      `<span class="fc-cat-letter">${esc(c.letter)}</span>${esc(c.name)}</button>`;

    let rows = '';
    for (const [ring, chips] of byRing) {
      rows += `<div class="fc-cat-row">` +
        `<span class="fc-cat-ring">${esc(ring)}</span>` +
        `<div class="fc-cat-chips">${chips.map(chip).join('')}</div></div>`;
    }
    if (other) {
      rows += `<div class="fc-cat-row fc-cat-row-other">` +
        `<div class="fc-cat-chips">${chip(other)}</div></div>`;
    }
    return `<div class="fc-cats" role="group" aria-label="Filter by category">${rows}</div>`;
  }

  // Tag chips (#tag), multi-select.
  function tagBar() {
    if (!topics.length) return '';
    const chips = topics.map((t) =>
      `<button class="fc-filter${selectedTags.has(t) ? ' active' : ''}" type="button" ` +
      `data-tag="${esc(t)}" aria-pressed="${selectedTags.has(t)}">#${esc(t)}</button>`
    ).join('');
    return `<div class="fc-tags" role="group" aria-label="Filter by tag">${chips}</div>`;
  }

  // The decorative progress ribbon (placeholder values; see FEED_PROGRESS). It is
  // aria-hidden so it never reads as a heading — the fill is animated after paint.
  function ribbonHTML() {
    const { pct, now } = FEED_PROGRESS;
    return `<div class="ribbon" aria-hidden="true">` +
      `<div class="ribbon-track"><div class="ribbon-fill" data-pct="${esc(pct)}"></div></div>` +
      `<div class="ribbon-label"><span>Your path · <b>${esc(pct)}%</b> through CODER</span>` +
      `<span>Now · ${esc(now)}</span></div></div>`;
  }

  // Group-by-day toggle + a Hide-flagged toggle + a Clear control (shown only when a
  // filter is active). Hide flagged is OFF by default; ON drops flagged posts from the
  // list (includeFlagged:false in paint). Same control-chip language + aria-pressed.
  function controlsBar() {
    const anyFilter = selectedCategories.size || selectedTags.size;
    const clear = anyFilter
      ? `<button class="fc-ctl fc-clear" type="button" data-clear="1">Clear filters</button>` : '';
    return `<div class="fc-controls">` +
      `<button class="fc-ctl fc-group${groupByDay ? ' active' : ''}" type="button" data-group="1" ` +
      `aria-pressed="${groupByDay}">Group by day</button>` +
      `<button class="fc-ctl fc-hideflagged${hideFlagged ? ' active' : ''}" type="button" data-hideflagged="1" ` +
      `aria-pressed="${hideFlagged}">Hide flagged</button>${clear}</div>`;
  }

  // ── AUTH AREA (Step 4) ─────────────────────────────────────────────────────
  // Browsing is OPEN — this only gates posting/flagging (Steps 5/6). Signed out:
  // a "Sign in with Google" button, plus (when DEV_MOCK) a muted "Dev sign-in",
  // plus a one-line note that signing in is only needed to post or flag. Signed
  // in: a compact user chip (avatar + name + email + sign out). The avatar is
  // aria-hidden; the name carries the text. Errors land in an aria-live toast.
  function authArea() {
    const session = getCurrentSession();
    if (isSignedIn() && session) {
      const initials = esc(session.initials || (session.name || '?').slice(0, 2).toUpperCase());
      // "New post" trigger — shown ONLY when signed in (gates posting; Step 5). Opens
      // the composer. Signed-out users see sign-in instead, never this.
      return `<div class="feed-auth" data-auth="in">` +
        `<button class="auth-btn auth-newpost" type="button" data-newpost="1">＋ New post</button>` +
        `<div class="user-chip">` +
        `<div class="user-avatar" aria-hidden="true">${initials}</div>` +
        `<div class="user-who"><span class="user-name">${esc(session.name || 'Signed in')}</span>` +
        `<span class="user-email">${esc(session.email || '')}</span></div>` +
        `<button class="auth-btn auth-signout" type="button" data-signout="1">Sign out</button>` +
        `</div></div>`;
    }
    // Signed out.
    const dev = DEV_MOCK
      ? `<button class="auth-btn auth-dev" type="button" data-dev-signin="1">Dev sign-in</button>` : '';
    return `<div class="feed-auth" data-auth="out">` +
      `<div class="auth-actions">` +
      `<button class="auth-btn auth-google" type="button" data-google-signin="1">` +
      `<span class="auth-g" aria-hidden="true">G</span> Sign in with Google</button>${dev}` +
      `</div>` +
      `<p class="auth-note">Signing in is only needed to post or flag — browsing is open.</p>` +
      `</div>`;
  }

  // A small aria-live toast region; messages are announced to assistive tech.
  // tone: 'ok' (confirmation) | 'error' (rejection / not configured).
  function showToast(msg, tone) {
    let el = mount.querySelector('.feed-toast');
    if (!el) return; // toast region only exists after a paint
    el.textContent = msg;
    el.className = 'feed-toast show ' + (tone === 'error' ? 'is-error' : 'is-ok');
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.className = 'feed-toast'; el.textContent = ''; }, 5200);
  }

  async function paint() {
    // A full repaint rebuilds innerHTML, so any injected inline flag-confirm is gone —
    // drop the dangling reference (no focus bounce: the trigger is being replaced too).
    openConfirm = null;
    const posts = await listPosts({
      categories: [...selectedCategories],
      tags: [...selectedTags],
      includeFlagged: !hideFlagged
    });

    // Capture the focused control just before innerHTML wipes it — unless a handler has
    // already set an explicit nextFocus (a transform case), which takes precedence below.
    if (!nextFocus) pendingFocus = stableSelector(document.activeElement);

    mount.innerHTML = `<div class="feed">` +
      `<div class="feed-head"><div class="feed-head-row">` +
      `<h1 class="feed-title">The Feed</h1>${authArea()}</div>` +
      `<p class="feed-sub">Field notes from the practice — newest first. Social, not the syllabus.</p></div>` +
      `<div class="feed-toast" role="status" aria-live="polite"></div>` +
      ribbonHTML() +
      `<div class="feed-filterbar">${categoryBar()}${tagBar()}${controlsBar()}</div>` +
      listHTML(posts) +
      `</div>`;
    runMermaid(mount);

    // Animate the ribbon fill from 0 → pct after paint (next frame so the
    // transition runs). Decorative only — see FEED_PROGRESS.
    const fill = mount.querySelector('.ribbon-fill');
    if (fill) setTimeout(() => { fill.style.width = (fill.dataset.pct || 0) + '%'; }, 60);

    // Restore keyboard focus. An explicit nextFocus (transform case) wins; otherwise the
    // captured pendingFocus. Both are consumed once. preventScroll so a routine filter
    // toggle never yanks the viewport. Null-guarded throughout — a miss is a no-op, never
    // a throw and never a stray focus.
    const target = nextFocus || pendingFocus;
    nextFocus = null;
    pendingFocus = null;
    if (target) mount.querySelector(target)?.focus({ preventScroll: true });
  }

  // One delegated click handler, de-duped across re-entry (inert when Feed isn't mounted).
  if (mount._feedClick) mount.removeEventListener('click', mount._feedClick);
  mount._feedClick = function (e) {
    const cat = e.target.closest('.fc-cat');
    if (cat) {
      const id = cat.dataset.cat;
      if (selectedCategories.has(id)) selectedCategories.delete(id); else selectedCategories.add(id);
      paint(); return;
    }
    // tag chips live both in the filter bar (.fc-filter) and in each card footer (.fc-topic)
    const tagChip = e.target.closest('.fc-filter');
    if (tagChip && tagChip.dataset.tag != null) {
      toggleTag(tagChip.dataset.tag); return;
    }
    const footerTag = e.target.closest('.fc-topic');
    if (footerTag) { toggleTag(footerTag.dataset.topic || ''); window.scrollTo(0, 0); return; }
    const group = e.target.closest('.fc-group');
    if (group) { groupByDay = !groupByDay; paint(); return; }
    const hideFlag = e.target.closest('.fc-hideflagged');
    if (hideFlag) { hideFlagged = !hideFlagged; paint(); window.scrollTo(0, 0); return; }
    const clear = e.target.closest('.fc-clear');
    if (clear) {
      selectedCategories.clear();
      selectedTags.clear();
      paint(); window.scrollTo(0, 0); return;
    }
    const option = e.target.closest('.scn-opt');
    if (option && !option.disabled) { revealScenario(option); return; }
    // ── flag (Step 6): open inline confirm → Confirm calls store.flagPost → repaint ──
    const flagBtn = e.target.closest('[data-flag]');
    if (flagBtn && flagBtn.dataset.flag != null) { openFlagConfirm(flagBtn); return; }
    const flagYes = e.target.closest('[data-flag-confirm]');
    if (flagYes) { confirmFlag(flagYes.dataset.flagConfirm); return; }
    const flagNo = e.target.closest('[data-flag-cancel]');
    if (flagNo) { closeFlagConfirm(true); return; }
    // ── auth controls (Step 4) ──
    if (e.target.closest('[data-google-signin]')) { doGoogleSignIn(); return; }
    if (e.target.closest('[data-dev-signin]')) { doDevSignIn(); return; }
    if (e.target.closest('[data-signout]')) { doSignOut(); return; }
    // ── compose (Step 5) ──
    const newpost = e.target.closest('[data-newpost]');
    if (newpost) { doOpenComposer(newpost); return; }
  };
  mount.addEventListener('click', mount._feedClick);

  // ESC dismisses an open inline flag-confirm and returns focus to its Flag button —
  // a separate but equally de-duped listener (never two of either across re-entry).
  if (mount._feedKey) mount.removeEventListener('keydown', mount._feedKey);
  mount._feedKey = function (e) {
    if (e.key === 'Escape' && openConfirm) { e.preventDefault(); closeFlagConfirm(true); }
  };
  mount.addEventListener('keydown', mount._feedKey);

  // ── inline flag-confirm (accessible; NOT window.confirm) ───────────────────────
  // Only one confirm is open at a time. openConfirm holds { id, trigger } so Cancel/ESC
  // can return focus to the exact Flag button that opened it. The confirm row is injected
  // into that card's foot (no full repaint — open/close is local), and focus moves to its
  // Confirm button so the keyboard lands inside the group straight away.
  let openConfirm = null;
  function openFlagConfirm(flagBtn) {
    const id = flagBtn.dataset.flag;
    closeFlagConfirm(false);            // collapse any other open confirm first (no focus bounce)
    const foot = flagBtn.closest('.card-foot');
    if (!foot) return;
    openConfirm = { id, trigger: flagBtn };
    flagBtn.hidden = true;              // hide the Flag button while its confirm is up
    foot.insertAdjacentHTML('beforeend', flagConfirmHTML(id));
    const yes = foot.querySelector('.flag-confirm-yes');
    if (yes) yes.focus();
  }
  // Remove the open confirm. returnFocus=true restores focus to the Flag button (Cancel/ESC);
  // false is the silent teardown used when another confirm opens or the feed repaints.
  function closeFlagConfirm(returnFocus) {
    if (!openConfirm) return;
    const { trigger } = openConfirm;
    const row = mount.querySelector('.flag-confirm');
    if (row) row.remove();
    if (trigger) {
      trigger.hidden = false;
      if (returnFocus) trigger.focus();
    }
    openConfirm = null;
  }
  // Confirm → flagPost (store.js owns the count + the FLAG_THRESHOLD flip) → repaint so
  // the card picks up its flagged treatment → announce via the existing aria-live toast.
  // CLIENT-SIDE ONLY: this lands in feedStore.flags in THIS browser; cross-user flagging
  // and real deletion need the backend pass.
  async function confirmFlag(id) {
    openConfirm = null;                 // the row goes away with the repaint; drop the ref
    try {
      await flagPost(id);               // → store.js; at/above FLAG_THRESHOLD it sets status:'flagged'
    } catch (e) {
      showToast(e.message, 'error');
      return;
    }
    // Transform case: the Flag button is being replaced by a non-interactive "Flagged ·
    // Pending" indicator. Land focus on the flagged card's article (tabindex="-1") so the
    // keyboard never falls to <body>. If the card dropped from view (e.g. Hide-flagged),
    // querySelector misses and the restore is a harmless no-op.
    nextFocus = `[data-id="${CSS.escape(id)}"]`;
    repaintWithToast('Marked for review.', 'ok');
  }

  // Repaint just the head (keeps the toast region) then re-show a message.
  // Cheapest correct option this pass is a full paint — the list is small and the
  // head is part of the same innerHTML. Re-show the toast after, since paint clears it.
  async function repaintWithToast(msg, tone) {
    await paint();
    if (msg) showToast(msg, tone);
  }

  // Real Google sign-in. With an empty GOOGLE_CLIENT_ID the auth module throws a
  // readable "not configured" Error — we surface it in the toast (no crash) and,
  // since DEV_MOCK is on, the Dev sign-in button is already there to fall back to.
  async function doGoogleSignIn() {
    try {
      const session = await signInWithGoogle();
      // Transform case: the sign-in button is replaced by the user chip — land focus on
      // its Sign out button so the keyboard stays in the auth area, not on <body>.
      nextFocus = '.auth-signout';
      await repaintWithToast(`Signed in as ${session.name}.`, 'ok');
    } catch (err) {
      // Rejections: not configured, non-deptagency email, blocked popup, load failure.
      showToast(err && err.message ? err.message : 'Sign-in failed. Please try again.', 'error');
    }
  }

  function doDevSignIn() {
    try {
      const session = signInDevMock();
      // Transform case: same as Google — focus the new Sign out button after the chip
      // replaces the Dev sign-in button.
      nextFocus = '.auth-signout';
      repaintWithToast(`Signed in as ${session.name} (dev).`, 'ok');
    } catch (err) {
      showToast(err && err.message ? err.message : 'Dev sign-in is unavailable.', 'error');
    }
  }

  function doSignOut() {
    signOut();
    // Transform case: the user chip is replaced by the sign-in buttons — land focus on
    // the primary "Sign in with Google" button (always present signed out), so the
    // keyboard stays in the auth area.
    nextFocus = '.auth-google';
    repaintWithToast('Signed out.', 'ok');
  }

  // Open the composer (Step 5). The composer manages its own listeners and cleans them
  // up on close (no leak across opens); it gates on requireSession internally too. On a
  // successful post it calls back here — we repaint (the new createdAt sorts to the top)
  // and surface its toast. Focus returns to the trigger on close (handled by composer).
  async function doOpenComposer(trigger) {
    try {
      await openComposer({
        returnFocusTo: trigger,
        onPosted: (res) => {
          repaintWithToast((res && res.toast) || 'Posted.', (res && res.tone) || 'ok');
        }
      });
    } catch (err) {
      // requireSession threw (somehow signed out between paint and click) — surface it.
      showToast(err && err.message ? err.message : 'Please sign in to post.', 'error');
    }
  }

  function toggleTag(t) {
    if (!t) return;
    if (selectedTags.has(t)) selectedTags.delete(t); else selectedTags.add(t);
    paint();
  }

  // Tap an option: lock the set, mark the picked one, reveal the verdict. The
  // correct option always greens; a wrong pick also ochres (the .correct/.wrong
  // states from Step 3, on top of the new .scn-opt look).
  function revealScenario(option) {
    const sc = option.closest('.card--scenario');
    if (!sc) return;
    option.classList.add('picked');
    sc.querySelectorAll('.scn-opt').forEach((b) => {
      b.disabled = true;
      if (b.dataset.correct === '1') b.classList.add('correct');
    });
    if (option.dataset.correct !== '1') option.classList.add('wrong');
    const reveal = sc.querySelector('.scn-reveal');
    if (reveal) reveal.classList.add('show');
  }

  await paint();
}
