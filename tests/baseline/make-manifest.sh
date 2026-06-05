#!/usr/bin/env bash
#
# make-manifest.sh — content fingerprint generator for the v2 parity safety net.
#
# Emits one line per content file:  <sha256>  <relative/path>  <bytecount>
# Sorted by path so the output is stable and diffable across phase gates.
#
# Scope (the three content surfaces that must survive the v2 restructure):
#   - content-architecture/**/*.json   (git-JSON source of truth)
#   - content-system/**/*.html         (frozen HTML monoliths)
#   - app/resources/**/*.html          (front-end resource pages: runbook, checklist, faqs)
#
# Usage (run from anywhere; paths are resolved relative to the repo root):
#   bash tests/baseline/make-manifest.sh                 # print to stdout
#   bash tests/baseline/make-manifest.sh > tests/baseline/content-manifest.txt
#
# Re-run at every phase gate and `diff` against the committed baseline.
# A zero-diff (modulo intentional path moves) proves no content drift.
#
# Idempotent: pure read-only hashing, no side effects. Deterministic output.
#
# Portability: prefers `sha256sum` (coreutils); falls back to `shasum -a 256`
# (BSD/macOS); falls back to python3 hashlib if neither is present.

set -euo pipefail

# Resolve repo root as the parent of tests/baseline/ (two levels up from this script).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Pick a hashing backend once.
if command -v sha256sum >/dev/null 2>&1; then
  HASH_CMD() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  HASH_CMD() { shasum -a 256 "$1" | awk '{print $1}'; }
elif command -v python3 >/dev/null 2>&1; then
  HASH_CMD() { python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }
else
  echo "ERROR: no sha256 backend (need sha256sum, shasum, or python3)" >&2
  exit 1
fi

# Portable byte count (wc -c is universal; strip leading whitespace).
bytecount() { wc -c < "$1" | tr -d '[:space:]'; }

# Collect the in-scope files. -print0 + sort -z keeps paths with spaces safe
# and gives deterministic ordering.
find \
  content-architecture -name '*.json' -type f -print0 \
  -o -path 'content-system/*' -name '*.html' -type f -print0 \
  -o -path 'app/resources/*' -name '*.html' -type f -print0 2>/dev/null \
| sort -z \
| while IFS= read -r -d '' f; do
    printf '%s  %s  %s\n' "$(HASH_CMD "$f")" "$f" "$(bytecount "$f")"
  done
