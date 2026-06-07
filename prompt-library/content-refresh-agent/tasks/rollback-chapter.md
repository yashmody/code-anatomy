# Rollback Chapter — Task

Restore a course chapter to a prior snapshot taken by the Content Refresh Agent.
Used by `*rollback`. Every auto-refresh snapshots the chapter first, so any
weekly write is reversible without data loss.

## Steps

1. **Identify the chapter.** Ask the user for the chapter `filename` (e.g.
   `adobe-cm.json`) if not supplied.

2. **List snapshots.** Show the `course_chapter_versions` rows for that chapter
   as a numbered list — `version id · captured_at · reason` — newest first.

3. **Confirm the target.** Ask the user to pick the version to restore. Show a
   short diff summary (which sections differ) between the current chapter and the
   chosen snapshot. Require explicit confirmation.

4. **Snapshot-then-restore.** Snapshot the CURRENT chapter first (reason:
   `pre-rollback <date>`) so the rollback is itself reversible, then write the
   chosen snapshot's content back into `course_chapters`.

5. **Invalidate + verify.** Fire the cache-invalidation webhook; confirm the
   live chapter now matches the restored version.

6. **Report.** State what was restored, from which version, and the new
   `pre-rollback` snapshot id (in case they want to redo).

## Guardrail

Rollback restores the WHOLE chapter content JSON from a snapshot. Because the
agent only ever wrote the `auto-adobe-updates` block, a rollback effectively
reverts that block — curated prose in the snapshot is identical to current. If
the curated prose was changed by a human between snapshot and now, warn the user
that those edits exist in the current version and confirm before overwriting.
