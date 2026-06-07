"""Weekly Adobe content-refresh sync — cron entrypoint (Phase 1).

Fetches the allow-listed Adobe release-notes pages, extracts + summarises the
latest updates with Claude, and stores new ones in `whats_new_items` (served by
GET /api/whatsnew). Honours the master switch `content_refresh_enabled`.

Usage:
    python -m scripts.sync_adobe_updates                 # respects the enable flag
    python -m scripts.sync_adobe_updates --dry-run       # fetch+summarise, NO writes
    python -m scripts.sync_adobe_updates --force         # run even if disabled (one-off)

Exit codes: 0 = ran (or correctly skipped because disabled); 1 = error.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core import config
from app.modules.whatsnew import service


def main() -> int:
    ap = argparse.ArgumentParser(description="Weekly Adobe content-refresh sync.")
    ap.add_argument("--dry-run", action="store_true", help="Fetch + summarise but write nothing")
    ap.add_argument("--force", action="store_true", help="Run even when content_refresh_enabled is false")
    ap.add_argument("--json", action="store_true", help="Print the full report as JSON")
    args = ap.parse_args()

    enabled = config.settings.content_refresh_enabled
    print(f"[sync] enabled={enabled} schedule={config.settings.content_refresh_cron!r} "
          f"tz={config.settings.content_refresh_tz} provider={config.settings.llm_provider}")

    if not enabled and not args.force:
        print("[sync] content_refresh_enabled is false — skipping. "
              "Use --force for a one-off (e.g. the pre-enable dry run).")
        return 0

    report = asyncio.run(service.run_sync(dry_run=args.dry_run))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        mode = "DRY-RUN" if report.get("dry_run") else "LIVE"
        print(f"[sync] {mode} · model={report.get('model')} · new items={report.get('new_items')}")
        for s in report.get("sources", []):
            line = f"  {s['key']:9} fetched={s.get('fetched')} extracted={s.get('extracted',0)} new={s.get('new',0)}"
            if s.get("error"):
                line += f"  ERROR: {s['error']}"
            print(line)
            for it in s.get("items", [])[:6]:
                print(f"       • [{it.get('date') or '—'}] {it['title']}")
        for e in report.get("errors", []):
            print(f"  ! {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
