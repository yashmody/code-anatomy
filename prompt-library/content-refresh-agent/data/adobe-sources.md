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

> Build-time TODO: pin the exact RSS/Atom URL (preferred) or release-notes page +
> parser for each key. Prefer feeds; fall back to an HTML adapter only where no
> feed exists. Store the resolved URLs in config/DB so ops can re-point them
> without a code change.

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
