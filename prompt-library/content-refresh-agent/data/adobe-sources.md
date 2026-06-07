# Adobe Sources — Allow-list & Knowledge Base

The Content Refresh Agent fetches ONLY from the hosts/feeds listed here. No
user-supplied or off-list URL is ever fetched (SSRF/egress guard). Exact feed
URLs are confirmed live at build time — some Adobe products publish RSS/Atom;
others need an HTML release-notes adapter.

## Tracked areas (chosen)

| Key | Area | Typical source |
|---|---|---|
| `commerce` | Adobe Commerce (Magento) | Commerce release notes / developer changelog |
| `aem` | Adobe Experience Manager incl. AEMaaCS | Experience League AEM release notes |
| `ajo` | Adobe Journey Optimizer | Experience League AJO release notes |
| `cja` | Customer Journey Analytics | Experience League CJA release notes |
| `target` | Adobe Target / A-B | Experience League Target release notes |
| `campaign` | Adobe Campaign | Experience League Campaign release notes |

> Implemented (Phase 1): the exact release-notes URLs are pinned in
> `backend/app/modules/whatsnew/sources.py` (the runtime source of truth). The
> Experience League pages are server-rendered but expose no RSS, so the pipeline
> fetches the page text and uses Claude to extract + summarise the latest entries
> (no brittle HTML parsing, no extra dependency). Note: the Commerce *overview*
> page is an index without datable entries — it fetches cleanly but yields 0
> items; point it at a specific release page if per-item Commerce updates are
> wanted.

## Fetch rules

- Allow-list by HOST. Reject any redirect that leaves the allow-listed host.
- Per-request timeout and response-size cap.
- Dedup key = canonical `source_url` (or feed GUID).
- A failing source is logged and skipped — never aborts the run.

## Course-chapter classification targets

Claude classifies each item to one of the known chapters (or `none`). The Adobe
ring chapters are the primary targets:

- `adobe-cm.json` (Content Management / AEM), `adobe-aa.json` (Analytics),
  `adobe-cja.json` (CJA), `adobe-ajo.json` (AJO), `adobe-camp.json` (Campaign),
  `adobe-csc.json` (Commerce / Storefront), `adobe-ab.json` (A-B / Target).

Only chapters that opt into an `auto-adobe-updates` block receive automatic
writes (see the governance checklist).

## Reference

Full architecture, data model, scheduler, and the bounded-refresh rationale:
`docs/architecture/v2/whats-new-pipeline.md`.
