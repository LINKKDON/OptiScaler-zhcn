#!/usr/bin/env python3
"""Prove that the Chinese strings really made it into the built DLL.

The old fork never looked at the artifact: a green build only meant that
MSBuild exited 0, not that the binary contained a single translated glyph. A
mislabelled encoding (cl.exe reading the injected UTF-8 source with the system
ANSI code page) or a silently skipped injection both produce a DLL that builds
fine and renders nothing, so the check has to be done on bytes, not on logs.

What this checks
----------------
Every ``--expect-utf8`` value is encoded to UTF-8 and searched for as a raw
byte sequence in the file. Finding it proves two things at once:

* the translation reached the compiler (the injection ran), and
* it was encoded as UTF-8 in the binary (``/utf-8`` was in effect), because a
  mojibake build would store the same characters under a different byte
  sequence (typically the ANSI code page, or UTF-16 for wide literals).

Limitations, stated on purpose
------------------------------
* A byte match is necessary, not sufficient. It cannot prove that the string is
  reachable from the menu; it only proves the bytes are present. Use it as a
  tripwire for encoding/injection regressions, not as a functional test.
* A UTF-16 encoded literal would not match, which is intended: this build
  compiles the menu strings as narrow ``char`` literals.
* Compilers are allowed to drop unreferenced literals, so an assertion must
  name a string the menu actually displays. ``--expect-utf8`` values are
  therefore taken from dict_v10.json values, not invented.

Usage:
    python tools_cn/verify_binary.py --dll x64/Release/a/OptiScaler.dll \
        --expect-utf8 重投影设置 --expect-utf8 正在打开 ImGui
"""
import argparse
import sys
from pathlib import Path


def find_all(haystack: bytes, needle: bytes) -> list:
    """Return every offset at which *needle* occurs in *haystack*."""
    offsets = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return offsets
        offsets.append(idx)
        start = idx + 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Assert that UTF-8 encoded Chinese strings are present in a "
                    "built OptiScaler.dll. Exits non-zero when any of them is "
                    "missing, which means the localization or the /utf-8 compile "
                    "flag did not take effect.")
    ap.add_argument("--dll", type=Path, required=True,
                    help="path to the built OptiScaler.dll")
    ap.add_argument("--expect-utf8", action="append", default=[], metavar="TEXT",
                    help="a string that must appear UTF-8 encoded in the binary "
                         "(repeatable)")
    ap.add_argument("--expect-utf16", action="append", default=[], metavar="TEXT",
                    help="a string that must appear UTF-16LE encoded in the binary "
                         "(repeatable; for wide-character literals)")
    ap.add_argument("--show-bytes", action="store_true",
                    help="also print the expected byte sequence in hex")
    args = ap.parse_args()

    if not args.expect_utf8 and not args.expect_utf16:
        print("ERROR: at least one --expect-utf8 or --expect-utf16 is required; "
              "an empty invocation would pass unconditionally", file=sys.stderr)
        return 2
    if not args.dll.is_file():
        print(f"ERROR: dll not found: {args.dll}", file=sys.stderr)
        return 2

    blob = args.dll.read_bytes()
    print(f"binary: {args.dll} ({len(blob)} bytes)")

    failures = 0

    for text in args.expect_utf8:
        needle = text.encode("utf-8")
        hits = find_all(blob, needle)
        if hits:
            shown = ", ".join(f"0x{o:X}" for o in hits[:5])
            extra = "" if len(hits) <= 5 else f" (+{len(hits) - 5} more)"
            print(f"  OK   utf-8  {text!r}  {len(needle)} bytes at {shown}{extra}")
        else:
            failures += 1
            print(f"  FAIL utf-8  {text!r} not found in the binary", file=sys.stderr)
            print(f"         expected bytes: {needle.hex(' ')}", file=sys.stderr)
            if args.show_bytes:
                print(f"         codepoints: {' '.join(f'U+{ord(c):04X}' for c in text)}",
                      file=sys.stderr)

    for text in args.expect_utf16:
        needle = text.encode("utf-16-le")
        hits = find_all(blob, needle)
        if hits:
            shown = ", ".join(f"0x{o:X}" for o in hits[:5])
            extra = "" if len(hits) <= 5 else f" (+{len(hits) - 5} more)"
            print(f"  OK   utf-16 {text!r}  {len(needle)} bytes at {shown}{extra}")
        else:
            failures += 1
            print(f"  FAIL utf-16 {text!r} not found in the binary", file=sys.stderr)
            print(f"         expected bytes: {needle.hex(' ')}", file=sys.stderr)

    if failures:
        print(f"binary verification FAILED ({failures} missing string(s))", file=sys.stderr)
        print("  A missing UTF-8 string means the localization ran but the source "
              "was not read as UTF-8 (check CL=/utf-8), or the injection step was "
              "skipped.", file=sys.stderr)
        return 1

    total = len(args.expect_utf8) + len(args.expect_utf16)
    print(f"binary verification OK ({total} string(s) present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
