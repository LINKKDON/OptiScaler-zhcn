#!/usr/bin/env python3
"""Render a Release notes template with values taken from the environment.

The templates live in ``.github/release-notes-*.md`` and use ``{{NAME}}``
placeholders. Keeping them out of the workflow YAML avoids the quoting minefield
of embedding a long multi-line string inside a ``run: |`` block, and makes the
text reviewable as plain Markdown.

Usage:
    python tools_cn/render_notes.py \\
        --template .github/release-notes-auto.md \\
        --out dist/notes.md \\
        --require ARCHIVE VERSION UPSTREAM_SHA

Any ``{{NAME}}`` that is not present in the environment is a hard error, so a
typo in the template can never ship a release note with a literal placeholder.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def _force_utf8_stdio() -> None:
    """Make print() safe on hosts whose stdio defaults to a legacy code page.

    Diagnostics echo template placeholders and the Chinese notes themselves, so
    an error path must not die with UnicodeEncodeError.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_force_utf8_stdio()



def main() -> int:
    ap = argparse.ArgumentParser(description="Render the release notes template")
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--require", nargs="*", default=[],
                    help="extra placeholder names that must be present")
    args = ap.parse_args()

    if not args.template.exists():
        print(f"ERROR: template not found: {args.template}", file=sys.stderr)
        return 2

    template = args.template.read_text(encoding="utf-8")
    names = sorted(set(PLACEHOLDER.findall(template)) | set(args.require))

    values: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            missing.append(name)
        else:
            values[name] = raw

    if missing:
        print(f"ERROR: missing environment values for: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    def substitute(match: re.Match) -> str:
        return values[match.group(1)]

    rendered = PLACEHOLDER.sub(substitute, template)
    leftover = PLACEHOLDER.findall(rendered)
    if leftover:
        print(f"ERROR: unresolved placeholders: {', '.join(sorted(set(leftover)))}",
              file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered if rendered.endswith("\n") else rendered + "\n")

    print(f"wrote {args.out} ({args.out.stat().st_size} bytes, "
          f"{len(names)} placeholders: {', '.join(names)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
