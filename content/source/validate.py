#!/usr/bin/env python3
"""
Validate CODE-CODER content against the JSON Schemas and the framework spine.

Runs three layers JSON Schema can't do alone:
  1. Schema validation  — each file matches its schema (course / feed /
                          framework-explainer)
  2. Reference integrity — every frameworkAddress / frameworkRef resolves to a
     real address defined in course/framework.json
  3. Sub-section prefix  — each sub-section id shares its chapter's ring prefix

Usage:  python3 validate.py
Exit 0 = all valid; exit 1 = errors printed. Designed for CI.
"""
import json, glob, sys, pathlib
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).parent

def load(p): return json.load(open(ROOT / p))

def framework_addresses():
    fw = load("course/framework.json")
    addrs = set()
    for ring in fw["rings"]:
        addrs.add(ring["id"])
        for l in ring.get("letters", []): addrs.add(l["id"])
        for m in ring.get("modules", []): addrs.add(m["id"])
    return addrs

# AC1: named helper — the ring is the first dot-segment of a frameworkAddress.
# Used for the sub-section prefix check below; extracted so no future reader
# reaches for the filename to derive the ring.
def ring_from_address(addr: str) -> str:
    return addr.split('.')[0]

def main():
    errors, checked = [], 0
    addrs = framework_addresses()
    course_schema    = Draft202012Validator(load("schemas/course.schema.json"))
    feed_schema      = Draft202012Validator(load("schemas/feed.schema.json"))
    explainer_schema = Draft202012Validator(load("schemas/framework-explainer.schema.json"))

    # ---- Course sections ----
    for f in sorted(glob.glob(str(ROOT / "course/sections/*.json"))):
        rel = pathlib.Path(f).relative_to(ROOT)
        doc = json.load(open(f))
        checked += 1
        for e in course_schema.iter_errors(doc):
            errors.append(f"{rel}: {'/'.join(map(str, e.path))}: {e.message}")
        if doc.get("frameworkAddress") not in addrs:
            # BLOCKING gate: an unresolved frameworkAddress means the chapter is
            # disconnected from the framework spine — CI must not pass.
            # (CI wiring is the harness-gap follow-on; this exit is the contract.)
            errors.append(f"{rel}: frameworkAddress '{doc.get('frameworkAddress')}' not in framework.json")
        # sub-section ids should sit under the chapter's ring prefix
        for s in doc.get("sections", []):
            if not s["id"].startswith(ring_from_address(doc.get("frameworkAddress") or "")):
                errors.append(f"{rel}: sub-section id '{s['id']}' doesn't share the ring prefix")

    # ---- Feed items ----
    for f in sorted(glob.glob(str(ROOT / "feed/*.json"))):
        rel = pathlib.Path(f).relative_to(ROOT)
        doc = json.load(open(f))
        items = doc.get("feed", []) if isinstance(doc, dict) else doc
        for item in items:
            checked += 1
            for e in feed_schema.iter_errors(item):
                errors.append(f"{rel} [{item.get('id','?')}]: {e.message}")
            ref = item.get("frameworkRef")
            if ref and ref not in addrs:
                # BLOCKING gate: an unresolved frameworkRef disconnects a feed item
                # from the framework spine — CI must not pass.
                errors.append(f"{rel} [{item['id']}]: frameworkRef '{ref}' not in framework.json")
            # 100-word guard on posts
            if item.get("type") == "post":
                wc = len(item.get("body", "").split())
                if wc > 100:
                    errors.append(f"{rel} [{item['id']}]: post body is {wc} words (max 100)")

    # ---- Framework explainer (single file, AC2) ----
    explainer_path = ROOT / "course" / "framework-explainer.json"
    explainer_rel  = explainer_path.relative_to(ROOT)
    checked += 1
    doc = json.load(open(explainer_path))
    for e in explainer_schema.iter_errors(doc):
        errors.append(f"{explainer_rel}: {'/'.join(map(str, e.path))}: {e.message}")

    print(f"Checked {checked} content items against schemas + framework spine.")
    if errors:
        print(f"\n{len(errors)} ERROR(S):")
        for e in errors: print("  -", e)
        sys.exit(1)
    print("All valid. Schemas pass. Every framework reference resolves.")

if __name__ == "__main__":
    main()
