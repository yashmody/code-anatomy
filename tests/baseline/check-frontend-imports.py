#!/usr/bin/env python3
"""Resolve every relative ES-module import in frontend/ and fail on any miss.

The backend smoke (tests/baseline/smoke.sh) never loads the front-end JS, so a
broken relative import (a file moved/renamed without its importers updated)
passes every backend gate silently and only breaks in the browser. This check
closes that gap: it statically resolves each `import ... from './x'` /
`import('./x')` against the filesystem and exits non-zero if any target is
missing.

Added in Phase 4b after three such imports (survivors of the Phase 1 reorg —
`./load.js`, `../render/diagram.js`) were found only when the moderator view
reused feed rendering. Run it at every gate that touches frontend/.

Usage:  python3 tests/baseline/check-frontend-imports.py
Exit:   0 = all resolve, 1 = one or more broken (listed).
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
ROOT = os.path.normpath(ROOT)

# `import ... from '<spec>'`, `export ... from '<spec>'`, and dynamic `import('<spec>')`.
IMPORT_RE = re.compile(
    r"""(?:import|export)\b[^'"]*\bfrom\s*['"]([^'"]+)['"]"""
    r"""|import\s*\(\s*['"]([^'"]+)['"]\s*\)"""
)


def main() -> int:
    broken = []
    checked = 0
    for dirpath, _dirs, files in os.walk(ROOT):
        for fname in files:
            if not fname.endswith(".js"):
                continue
            path = os.path.join(dirpath, fname)
            try:
                src = open(path, encoding="utf-8").read()
            except OSError:
                continue
            for match in IMPORT_RE.finditer(src):
                spec = match.group(1) or match.group(2)
                if not spec or not spec.startswith("."):
                    continue  # bare / CDN / absolute specifiers are out of scope
                checked += 1
                target = os.path.normpath(os.path.join(dirpath, spec))
                if not os.path.exists(target):
                    broken.append((os.path.relpath(path), spec, os.path.relpath(target)))

    print(f"checked {checked} relative imports across frontend/")
    if broken:
        print(f"\nBROKEN ({len(broken)}):")
        for path, spec, target in broken:
            print(f"  {path}\n     imports '{spec}'  ->  MISSING {target}")
        return 1
    print("ALL RELATIVE IMPORTS RESOLVE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
