# `docs-site/static/img/`

The docs-site image assets, populated in Phase 5. Everything here is small,
brand-derived and checked in so the build is self-contained — no fetch step at
build time.

## What is here

| File | Source / generation |
|---|---|
| `logo-dept.svg` | The canonical DEPT® logo, fetched once from `https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg` (see `CLAUDE.md`). All-black fills. Used in the navbar in light mode. Do not hand-edit — refresh from source. |
| `logo-dept-dark.svg` | `logo-dept.svg` with fills recoloured white, for the dark-mode navbar (`navbar.logo.srcDark`). Regenerate with `sed 's/fill="black"/fill="white"/g'` after refreshing the source logo. |
| `favicon.svg` | The DEPT® asterisk mark, white on an ochre `#FF4900` rounded tile. Hand-authored SVG; the render source for `favicon.png`. |
| `favicon.png` | 64×64 PNG rendered from `favicon.svg` (headless Chrome). Referenced as the site favicon — Docusaurus serves PNG favicons fine, so no `.ico` is needed. |
| `social-card.png` | 1200×630 OG / social preview card. Ink background, ochre accent and mark, the v2 wordmark. Rendered from `social-card.svg`. |

## Regenerating the rendered PNGs

`sips` cannot read SVG on this box, so the PNGs are rendered with headless
Chrome:

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --default-background-color=00000000 \
  --screenshot=favicon.png --window-size=64,64 "file://$PWD/favicon.svg"
"$CHROME" --headless --disable-gpu \
  --screenshot=social-card.png --window-size=1200,630 "file://$PWD/social-card.svg"
```

The brand fonts do not load in headless Chrome (no network for Google Fonts),
so the social card falls back to system fonts — the layout, ochre accent and
mark are what matter for the OG image.

## Brand sympathy

- Accent: `#FF4900` ochre — the only accent.
- Logo URL of record: `https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg`.
- Fonts (loaded via Google Fonts in `src/css/custom.css`): Syne, DM Sans,
  JetBrains Mono.
