# `docs-site/static/img/`

This folder holds the docs-site image assets. **Phase 0 leaves it empty on
purpose** — Phase 5a populates it.

## What Phase 5a places here

| File | Source / generation |
|---|---|
| `logo-dept.svg` | Fetched at build from `https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg` (the canonical DEPT® logo URL — see `CLAUDE.md`). Do not hand-edit; refresh from source. |
| `favicon.ico` | Generated from `logo-dept.svg` (ochre `#FF4900` background, ink mark). |
| `social-card.png` | OG / social preview card. 1200x630. Ochre accent, Syne display, the v2 wordmark. |
| `architecture/*.png` | Optional exported renders of the ASCII / Mermaid diagrams for sharing in slide decks. The site itself uses inline Mermaid. |

## Why no binaries are checked in at Phase 0

The scaffold deliverable is *files only, no `node_modules`* and no large
binaries. Each binary above is small but better added in the same commit
as the page that uses it.

## Brand sympathy

- Accent: `#FF4900` ochre.
- Logo URL of record: `https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg`.
- Fonts (loaded via Google Fonts in `src/css/custom.css`): Syne, DM Sans,
  JetBrains Mono.
