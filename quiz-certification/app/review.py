"""CLI: review saved quiz attempts.

Usage:
    python -m app.review                          # list all attempts
    python -m app.review <file.json>              # show details of one attempt
    python -m app.review --user yash@deptagency.com  # filter by user
    python -m app.review --stats                  # summary stats across all attempts

This module also exposes load() and summarize() for programmatic use.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import config, storage


def load(path: Path) -> Dict:
    """Load a single result JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def summarize(records: List[Dict]) -> Dict:
    if not records:
        return {"count": 0}
    passed = sum(1 for r in records if r.get("passed"))
    failed = len(records) - passed
    avg = sum(r.get("score", 0) for r in records) / len(records)
    by_diff = {}
    for r in records:
        d = r.get("difficulty", "unknown")
        by_diff.setdefault(d, {"count": 0, "passed": 0, "avg_score": 0.0})
        by_diff[d]["count"] += 1
        if r.get("passed"):
            by_diff[d]["passed"] += 1
        by_diff[d]["avg_score"] += r.get("score", 0)
    for d in by_diff:
        if by_diff[d]["count"]:
            by_diff[d]["avg_score"] /= by_diff[d]["count"]
    return {
        "count": len(records),
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / len(records),
        "avg_score": avg,
        "by_difficulty": by_diff,
    }


def _fmt_record(r: Dict, detailed: bool = False) -> str:
    out = []
    user = r.get("user", {})
    out.append(f"  ID:          {r.get('quiz_id', '?')}")
    out.append(f"  User:        {user.get('name', '')} <{user.get('email', '?')}>")
    out.append(f"  Difficulty:  {r.get('difficulty', '?')}")
    out.append(f"  Submitted:   {r.get('submitted_at', '?')}")
    out.append(
        f"  Result:      {'PASS' if r.get('passed') else 'FAIL'} · {r.get('correct', 0)}/{r.get('total', 0)} ({int(r.get('score', 0) * 100)}%)"
    )
    if r.get("cert_id"):
        out.append(f"  Cert ID:     {r['cert_id']}")
    if detailed:
        out.append("")
        out.append("  Questions:")
        for q in r.get("questions", []):
            qid = q["id"]
            ua_idx = r.get("user_answers", {}).get(qid)
            ca_idx = q.get("correct_index")
            mark = "✓" if ua_idx == ca_idx else "✗"
            out.append(f"    {mark} [{qid}] {q['question']}")
            for i, opt in enumerate(q.get("options", [])):
                marker = ""
                if i == ca_idx:
                    marker = "  ← correct"
                if i == ua_idx and i != ca_idx:
                    marker = "  ← user answered (wrong)"
                elif i == ua_idx and i == ca_idx:
                    marker = "  ← user answered (correct)"
                out.append(f"        {i}. {opt}{marker}")
            if q.get("explanation"):
                out.append(f"       » {q['explanation']}")
            out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Review saved Q0 quiz attempts.")
    parser.add_argument("file", nargs="?", help="Specific result JSON to inspect")
    parser.add_argument("--user", help="Filter by user email")
    parser.add_argument("--stats", action="store_true", help="Show summary statistics")
    parser.add_argument("--detailed", "-d", action="store_true", help="Show full question detail")
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        if not path.exists():
            path = config.QUIZ_RESULTS_DIR / args.file
        if not path.exists():
            print(f"File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        rec = load(path)
        print(f"\n=== Quiz attempt @ {path.name} ===")
        print(_fmt_record(rec, detailed=True))
        return

    if args.user:
        records = storage.attempts_for(args.user)
        header = f"=== Attempts for {args.user} ({len(records)}) ==="
    else:
        records = storage.all_attempts()
        header = f"=== All attempts ({len(records)}) ==="

    print(f"\n{header}\n")
    for r in records:
        print(_fmt_record(r, detailed=args.detailed))
        print("  ---")

    if args.stats:
        s = summarize(records)
        print("\n=== Summary ===")
        print(f"  Total:        {s['count']}")
        print(f"  Passed:       {s.get('passed', 0)}")
        print(f"  Failed:       {s.get('failed', 0)}")
        print(f"  Pass rate:    {int(s.get('pass_rate', 0) * 100)}%")
        print(f"  Avg score:    {int(s.get('avg_score', 0) * 100)}%")
        for diff, dstat in s.get("by_difficulty", {}).items():
            print(f"  {diff}: {dstat['count']} attempts · pass {dstat['passed']} · avg {int(dstat['avg_score'] * 100)}%")


if __name__ == "__main__":
    main()
