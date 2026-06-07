---
id: discovery-checklists
title: Discovery checklists
sidebar_position: 7
---

# Discovery checklists

The discovery checklist is the companion artifact to the Anatomy of Code course
and the runbooks — a structured list an architect works through during the
discovery phase of an engagement.

## Scan box

- **It is a packaged page, not a live collection.** The checklist ships as a
  static HTML file (`resources/checklists/code-coder-checklist.html`), carried
  over from the original monolith for visual parity.
- **No Directus authoring (yet).** Unlike course content, FAQs and runbooks,
  the checklist has no admin collection. It is a static asset.
- **Reach it from Resources.** It is linked from the SPA's Resources menu and
  served at `/resources/checklists/code-coder-checklist.html`.
- **Updating it is a code change.** Revising the checklist means editing the
  HTML file and redeploying — it is a developer/admin task, not an authoring
  one.

## Using the checklist

Open the SPA, go to **Resources → Checklist**, or visit
`/resources/checklists/code-coder-checklist.html` directly. Work top to bottom
during discovery; it pairs naturally with the
[architect runbook](./publishing-runbooks) and the relevant vertical FAQ.

## Updating the checklist

Because the checklist is a frozen artifact, changes go through the normal code
path:

1. A developer edits `resources/checklists/code-coder-checklist.html`.
2. The change is committed and deployed with the next release.

There is no live edit surface for it today.

:::info[Before / After]

**Before** — in the original monolith, every resource (course, checklist, FAQs)
was hand-edited HTML and shipped on deploy. **After** — course content, FAQs and
runbooks moved to the Directus write plane and update live. The checklist has not
made that jump yet; it is still a frozen page. If live-editable checklists become
a need, they would follow the same pattern as runbooks (a collection plus a
reader).

:::

:::note[Agency Tip]

If your team keeps refining the checklist, raise it as a candidate for the same
treatment runbooks got — a Directus collection and a dynamic reader. Until then,
batch your edits and hand them to a developer rather than chasing one-line
changes through deploys.

:::
