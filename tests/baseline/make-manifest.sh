#!/usr/bin/env bash
#
# make-manifest.sh — content fingerprint generator for the v2 parity safety net.
#
# Emits one line per content file:  <sha256>  <relative/path>  <bytecount>
# Sorted by path so the output is stable and diffable across phase gates.
#
# Scope (v2 paths — see docs/architecture/v2/01-blueprint.md §7):
#   - content/source/**/*.json   (git-JSON source of truth; was content-architecture/)
#   - content/frozen/**/*.html   (frozen HTML monolith + resource pages; was
#                                 content-system/ plus app/resources/, which
#                                 phase-1/C dedup'd into content/frozen/)
#
# Slice F (Phase 1) regenerates this manifest and asserts that the *sha256s*
# for every file match the pre-restructure baseline — paths change, content
# does not. The script ignores untracked files anywhere outside content/.
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
find content -type f \( -name '*.json' -o -name '*.html' \) -print0 2>/dev/null \
| sort -z \
| while IFS= read -r -d '' f; do
    printf '%s  %s  %s\n' "$(HASH_CMD "$f")" "$f" "$(bytecount "$f")"
  done
