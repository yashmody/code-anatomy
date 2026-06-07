# Content Refresh Governance Checklist

Run this BEFORE publishing any course write (task weekly-adobe-sync.md step 7.3).
Every item must be GREEN or the write is HELD, not shipped. This is the
mechanised slice of the CLAUDE.md content-quality mandate, applied to the bounded
`auto-adobe-updates` block.

## Scope & safety

- [ ] The write touches ONLY the `auto-adobe-updates` block — no curated prose
      section is added, removed, or modified.
- [ ] A snapshot of the chapter exists in `course_chapter_versions` from THIS run
      (rollback point) before any write.
- [ ] The change is additive within the block (replace the block wholesale with
      the new dated list — do not splice into curated content).

## Source integrity

- [ ] Every item in the block carries a real `source_url` from the allow-list.
- [ ] No fact, version number, or date appears that is not present in the source.
- [ ] No item is older/duplicated (dedup honoured).

## Brand & voice (DEPT®)

- [ ] Indian English spelling (organise, optimise, behaviour, centre).
- [ ] Plain professional register — no Americanisms, no hype, no "revolutionary".
- [ ] Acronyms expanded on first use (AEMaaCS, AJO, CJA, etc.).
- [ ] No AI-tells ("delve", "in today's fast-paced", "unlock", em-dash spam,
      "it's important to note", "as an AI").
- [ ] Ochre `#FF4900` and the existing block design language only — no new
      block type, no new colour.

## Structure & accessibility

- [ ] The block validates against the chapter content schema (renders without a
      fallback).
- [ ] Every source link is well-formed and resolves (link-integrity check).
- [ ] Links have descriptive text (not "click here"); any image has alt text.
- [ ] Heading level of the block is correct for its position (no skipped levels).

## Publish gate

- [ ] All boxes above are green → publish + fire cache invalidation.
- [ ] Any box red → set the item(s) `held`, do NOT write the chapter, record the
      failing check(s) in the run report.
- [ ] If satisfying a request would require editing curated prose → STOP and
      route to the human review queue (c0 → content-quality). Never auto-publish
      curated-prose changes.
