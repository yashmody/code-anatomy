# Content Refresh Agent (BMAD bundle)

A [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)-format agent that
keeps the DEPT® Anatomy-of-Code course and its **What's New** feed current with
the Adobe Experience Cloud — fetch → dedup → summarise (Claude) → publish What's
New → **governed, reversible** course refresh.

It is the operator persona for the pipeline specified in
`docs/architecture/v2/whats-new-pipeline.md`.

## Layout

```
content-refresh-agent/
├── agents/content-refresh.md                         # the agent (load this)
├── tasks/
│   ├── weekly-adobe-sync.md                           # *run-sync workflow
│   └── rollback-chapter.md                            # *rollback workflow
├── checklists/content-refresh-governance-checklist.md # the publish gate
├── data/
│   ├── adobe-sources.md                               # source allow-list + KB
│   └── refresh-config.yaml                            # enablement + Quartz schedule
└── templates/whats-new-item-tmpl.yaml                 # row + auto-block shape
```

## Use it

**In a BMAD project:** copy this folder into your `bmad-core/` (or `.bmad-core/`)
so the dependency paths resolve, then activate the agent
(`@content-refresh` / load `agents/content-refresh.md`). It greets as **Aria,
the Adobe Content Refresh Agent** and runs `*help`.

**Standalone (any agentic IDE/chat):** paste the contents of
`agents/content-refresh.md` as the system/agent prompt. It carries its full
persona, commands, and guardrails inline.

### Commands

`*help` · `*doctor` · `*run-sync` · `*fetch` · `*summarise` · `*whats-new` ·
`*refresh-course` · `*rollback` · `*status` · `*report` · `*enable` · `*disable` ·
`*schedule` · `*configure` · `*exit`

## Enablement & schedule

The agent runs only when switched on. Both the on/off state and the cadence live
in `data/refresh-config.yaml`:

```yaml
enablement:
  enabled: false                # master switch — flip to true to activate
  schedule: "0 0 9 ? * MON *"   # Quartz cron — every Monday at 09:00 (default)
  timezone: "Asia/Kolkata"      # IST
```

- **Quartz cron** (not Unix): `sec min hour day-of-month month day-of-week [year]`.
  The default `0 0 9 ? * MON *` = every Monday 09:00. Unix-cron equivalent for a
  VM crontab is `0 9 * * 1`.
- `*enable` / `*disable` flip the switch; `*schedule` shows or sets the Quartz
  expression (validated, with plain-English + Unix-cron echo).
- When `enabled: false`, scheduled runs are skipped and a manual `*run-sync` is
  refused unless explicitly forced.

## Guardrails (non-negotiable)

- Fetches ONLY the allow-listed Adobe sources (`data/adobe-sources.md`).
- Auto-writes ONLY the marked `auto-adobe-updates` block of a chapter — **never**
  curated prose. Broad prose changes route to the human review queue (c0 →
  content-quality), per `CLAUDE.md`.
- Snapshots every chapter before writing (`course_chapter_versions`) → one-command
  rollback.
- Validates against the governance checklist before publishing; failures are held.

## How it maps to the code

| Agent concept | Backend |
|---|---|
| Enablement + Quartz schedule | `content_refresh_enabled` / `content_refresh_cron` / `content_refresh_tz` in `config.py`; installer translates Quartz → the VM crontab line |
| `*run-sync` task | `backend/scripts/sync_adobe_updates.py` (cron: `infra/cron/adobe-sync.sh`) |
| Summaries | `config.llm_provider=anthropic` + `llm_api_key` |
| What's New | `whats_new_items` table + `GET /api/whatsnew` + SPA tab |
| Course refresh | `auto-adobe-updates` block + `course_chapter_versions` snapshot/rollback |
| Run report | SMTP/outbox seam (`backend/app/modules/quiz/email.py`) |

> The backend pieces are planned, not yet built (see the plan doc). The agent is
> usable now as the spec/operator; once the script exists, `*run-sync` drives it.
