#!/usr/bin/env python3
"""
Sanitise-lint for CODE-CODER course HTML fields.

Checks every innerHTML-rendered HTML string in the course corpus for:
  - Unknown tags (not in ALLOWED_TAGS)
  - Blocked attributes (only `class` is permitted; `style`, `rel`, `as`, `on*` etc. fail)
  - Dangerous attribute values: `javascript:` / `data:` in href/src/action
  - Event-handler attributes (on*)
  - <script> tags
  - Unbalanced tags (stack-based; void elements excluded from the stack)

Scope:
  - `html` field of blocks with type: chapter-open, lead, prose, heading, quote, callout
  - `notes` block `items[]` strings that contain `<`
  - Chapter-level `scan[]` strings that contain `<`

Excluded:
  - `content/source/course/framework-explainer.json` (schema-guarded separately by AC2)
  - Any `_note` field

Usage:
  python3 sanitise_lint.py          # check all chapters
  python3 sanitise_lint.py --check  # same, but semantically marks this as a CI gate

Exit 0 = all clean; exit 1 = violations found (file + block + reason printed).
"""

import glob
import json
import pathlib
import re
import sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).parent

# ---------------------------------------------------------------------------
# Allow-lists
# ---------------------------------------------------------------------------

ALLOWED_TAGS = frozenset({
    "b", "strong", "em", "code", "span", "div", "p", "br",
})

# Void elements are excluded from the open-tag stack (no closing tag expected).
VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

# Only `class` is permitted as a live HTML attribute in the course corpus.
# `style`, `rel`, `as`, and all event-handler attrs (on*) are blocked.
ALLOWED_ATTRS = frozenset({"class"})

# Block types whose `html` field is innerHTML-rendered and must be linted.
HTML_BLOCK_TYPES = frozenset({
    "chapter-open", "lead", "prose", "heading", "quote", "callout",
})

# Pattern matching dangerous URI scheme prefixes (case-insensitive).
_DANGEROUS_URI = re.compile(r"^\s*(javascript|data)\s*:", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Per-string checker
# ---------------------------------------------------------------------------

class _HtmlLinter(HTMLParser):
    """
    Single-use HTMLParser that collects violations from one HTML string.
    Instantiate, call feed(html), read .violations.
    """

    def __init__(self, location: str):
        super().__init__(convert_charrefs=False)
        self.location = location
        self.violations: list[str] = []
        self._stack: list[str] = []

    # ---- tag events --------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.violations.append(f"{self.location}: <script> tag is not allowed")

        if tag not in ALLOWED_TAGS and tag not in VOID_ELEMENTS:
            self.violations.append(
                f"{self.location}: unknown tag <{tag}> (not in allow-list)"
            )

        for attr, val in attrs:
            # Event-handler attributes (onclick, onload, etc.)
            if attr.startswith("on"):
                self.violations.append(
                    f"{self.location}: event-handler attribute '{attr}' on <{tag}>"
                )
                continue

            # Blocked named attributes
            if attr not in ALLOWED_ATTRS:
                self.violations.append(
                    f"{self.location}: attribute '{attr}' on <{tag}> is not in the allow-list"
                )
                continue

            # Safe-value check for href/src/action (belt-and-suspenders;
            # these attrs are blocked above, but guard against future allow-list widening)
            if attr in ("href", "src", "action") and val and _DANGEROUS_URI.match(val):
                self.violations.append(
                    f"{self.location}: dangerous URI scheme in {attr}=\"{val[:40]}\""
                )

        # Push non-void tags onto the balance stack.
        if tag not in VOID_ELEMENTS:
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_ELEMENTS:
            return
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        else:
            self.violations.append(
                f"{self.location}: unbalanced close </{tag}> "
                f"(stack top is {'<' + self._stack[-1] + '>' if self._stack else 'empty'})"
            )

    def close(self) -> None:
        super().close()
        if self._stack:
            self.violations.append(
                f"{self.location}: unclosed tag(s): "
                + ", ".join(f"<{t}>" for t in self._stack)
            )


def lint_html(html: str, location: str) -> list[str]:
    """Return a list of violation strings for the given HTML fragment."""
    # Hard-reject: HTML comments, CDATA sections, and processing instructions have
    # no legitimate use in course innerHTML fields and create a parser-differential
    # attack surface — html.parser swallows them as inert tokens, so a payload
    # hidden inside passes all tag/attr checks.  Reject on sight.
    for marker, label in (
        ("<!--",      "HTML comment (<!--)"),
        ("<![CDATA[", "CDATA section (<![CDATA[)"),
        ("<?",        "processing instruction (<?)"),
    ):
        if marker in html:
            return [f"{location}: {label} is not allowed in HTML fields"]
    checker = _HtmlLinter(location)
    checker.feed(html)
    checker.close()
    return checker.violations


# ---------------------------------------------------------------------------
# Corpus walker
# ---------------------------------------------------------------------------

def lint_file(path: pathlib.Path) -> list[str]:
    """Return all violations found in one section JSON file."""
    rel = path.relative_to(ROOT)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)

    violations: list[str] = []

    # Chapter-level scan[] items
    for i, item in enumerate(doc.get("scan", [])):
        if "<" in item:
            loc = f"{rel} [scan[{i}]]"
            violations.extend(lint_html(item, loc))

    # Block-level html fields + notes items
    for sec in doc.get("sections", []):
        sec_id = sec.get("id", "?")
        for j, blk in enumerate(sec.get("blocks", [])):
            btype = blk.get("type", "?")
            blk_loc = f"{rel} [section={sec_id} block[{j}] type={btype}]"

            if btype in HTML_BLOCK_TYPES:
                html = blk.get("html", "")
                if html:
                    violations.extend(lint_html(html, blk_loc))

            elif btype == "notes":
                for k, item in enumerate(blk.get("items", [])):
                    if "<" in item:
                        item_loc = f"{rel} [section={sec_id} block[{j}] notes.items[{k}]]"
                        violations.extend(lint_html(item, item_loc))

    return violations


def main() -> None:
    # --check is a semantic alias — same behaviour, marks this as a CI gate call.
    # (Kept for forward-compat; CI wiring is the harness-gap follow-on.)
    if "--check" in sys.argv:
        sys.argv.remove("--check")

    section_files = sorted(
        glob.glob(str(ROOT / "course" / "sections" / "*.json"))
    )

    all_violations: list[str] = []
    checked = 0

    for f in section_files:
        p = pathlib.Path(f)
        violations = lint_file(p)
        all_violations.extend(violations)
        checked += 1

    print(f"Sanitise-linted {checked} chapter files.")
    if all_violations:
        print(f"\n{len(all_violations)} VIOLATION(S):")
        for v in all_violations:
            print("  -", v)
        sys.exit(1)
    print("All clean. No disallowed tags, attributes, or dangerous values found.")


if __name__ == "__main__":
    main()
