#!/usr/bin/env python3
"""Localize the *comments* of the upstream OptiScaler.ini into Chinese.

Hard rule: this script only ever rewrites comment lines, i.e. lines whose first
non-blank character is ``;``. Section headers (``[Section]``) and every
``key=value`` line are passed through untouched, byte for byte. The generated
``OptiScaler.ini`` is therefore still a valid config file that upstream code
parses exactly like the original - only the human-readable comments differ.

Guarantees (all asserted by ``--check``):
  * section lines and key=value lines are byte-identical to the input
  * the number of comment lines, separator lines and total lines is unchanged
  * the ``;`` prefix and the number of spaces after it are preserved
  * markdown-ish markup inside a comment (``**bold**``, ``*emphasis*``, ``> ``
    blockquote, ``_italic_``, backticks, list numbers such as ``4.`` and hex or
    decimal literals) is preserved: a translation that drops or reorders a
    marker is rejected and the original line is kept
  * the file-level newline style (LF vs CRLF) and BOM state are preserved;
    in addition ``--check`` asserts the output is UTF-8 **without** BOM
  * idempotent: a second run produces a byte-identical file

The dictionary maps the comment text *without* the ``;`` prefix and without the
surrounding spaces to its Chinese translation::

    { "Enables Frame Generation": "启用帧生成" }

A comment that is not in the dictionary is kept as-is (never an error), so the
dictionary can grow incrementally. ``--report`` prints how many comments are
still untranslated.

Usage:
    python tools_cn/localize_ini.py --ini src/OptiScaler.ini --out dist/OptiScaler.ini
    python tools_cn/localize_ini.py --ini tools_cn/sample_OptiScaler.ini --check
    python tools_cn/localize_ini.py --ini src/OptiScaler.ini --report
    python tools_cn/localize_ini.py --ini src/OptiScaler.ini --lint-dict
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DICT = HERE / "dict_ini.json"

# A comment made only of rule characters is a visual separator and is never
# translated (translating it would also change its visual width).
SEPARATOR_RE = re.compile(r"^[;\s\-=*_~#+.]+$")

# Markers that must survive translation, in order, as a sequence.
EMPHASIS_RE = re.compile(r"\*\*|__|`|_|\*|^>|\s>\s|(?<!\w)#(?!\w)")
# Numeric literals / list numbers: "4.", "0x2D", "1.5", "255". Their multiset
# must be identical between source and translation.
NUMBER_RE = re.compile(r"0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?")


def split_comment(line: str):
    """Return (prefix, body, trailing) for a comment line, else None.

    prefix   the ``;`` plus every space directly after it
    body     the comment text (no trailing whitespace) - this is the dict key
    trailing whitespace that followed the text, preserved verbatim
    """
    stripped = line.lstrip()
    if not stripped.startswith(";"):
        return None
    indent = line[: len(line) - len(stripped)]
    rest = stripped[1:]
    m = re.match(r"[ \t]*", rest)
    gap = m.group(0)
    text_with_tail = rest[len(gap):]
    body = text_with_tail.rstrip()
    trailing = text_with_tail[len(body):]
    return indent + ";" + gap, body, trailing


def is_separator(line: str) -> bool:
    return bool(SEPARATOR_RE.match(line))


def structure(text: str):
    """Marker skeleton used to reject translations that break the layout."""
    emphasis = EMPHASIS_RE.findall(text)
    numbers = sorted(NUMBER_RE.findall(text))
    return emphasis, numbers


def load_dict(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: dictionary not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        print(f"ERROR: {path} has a UTF-8 BOM, expected none", file=sys.stderr)
        raise SystemExit(2)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        print(f"ERROR: {path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(data, dict):
        print(f"ERROR: {path} must contain a JSON object", file=sys.stderr)
        raise SystemExit(2)
    return data


class Stats:
    def __init__(self) -> None:
        self.comments = 0
        self.separators = 0
        self.translated = 0
        self.unchanged = 0
        self.missing = 0
        self.rejected = 0
        self.rejected_lines: list[tuple[int, str, str]] = []
        self.missing_texts: list[str] = []


def transform(lines: list[str], table: dict, force: bool = False) -> tuple[list[str], Stats]:
    """Translate comment lines. Everything else is returned unchanged."""
    stats = Stats()
    out: list[str] = []
    for idx, line in enumerate(lines):
        parts = split_comment(line)
        if parts is None:
            out.append(line)
            continue
        prefix, body, trailing = parts
        if not body:
            out.append(line)
            continue
        if is_separator(line):
            stats.separators += 1
            out.append(line)
            continue
        stats.comments += 1
        translated = table.get(body)
        if translated is None:
            stats.missing += 1
            stats.missing_texts.append(body)
            out.append(line)
            continue
        if not str(translated).strip():
            stats.rejected += 1
            stats.rejected_lines.append((idx + 1, body, "empty translation"))
            out.append(line)
            continue
        if "\n" in str(translated) or "\r" in str(translated):
            stats.rejected += 1
            stats.rejected_lines.append((idx + 1, body, "translation contains a newline"))
            out.append(line)
            continue
        if structure(body) != structure(str(translated)):
            if not force:
                stats.rejected += 1
                stats.rejected_lines.append(
                    (idx + 1, body, f"marker mismatch: {structure(body)} -> "
                                    f"{structure(str(translated))}"))
                out.append(line)
                continue
        if body == str(translated):
            # Either a deliberately latin-only entry (e.g. "1 = 2X | 2 = 3X")
            # or this file has already been translated. Counted separately so a
            # second run on an already localized ini reports translated = 0.
            stats.unchanged += 1
            out.append(line)
            continue
        stats.translated += 1
        out.append(prefix + str(translated) + trailing)
    return out, stats


def read_ini(path: Path) -> tuple[str, bool, str]:
    """Return (text, had_bom, newline) with the original text untouched."""
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text, had_bom, newline


def split_keep_endings(text: str) -> list[str]:
    """Split on LF only, dropping the LF; the writer re-adds the file's style.

    A CRLF file still carries the ``\\r`` at the end of every split piece, so it
    is stripped here - otherwise joining with ``"\\r\\n"`` would emit ``\\r\\r\\n``
    and every line would gain a stray CR on disk.
    """
    return [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]


def compare_guard(in_lines: list[str], out_lines: list[str]) -> list[str]:
    """Return a list of human readable violations (empty == no violation)."""
    problems: list[str] = []
    if len(in_lines) != len(out_lines):
        problems.append(f"line count changed: {len(in_lines)} -> {len(out_lines)}")
        return problems

    changed_non_comment = 0
    separator_delta = 0
    prefix_broken = 0
    examples: list[str] = []
    for idx, (a, b) in enumerate(zip(in_lines, out_lines), 1):
        if a == b:
            continue
        pa = split_comment(a)
        pb = split_comment(b)
        if pa is None or pb is None:
            changed_non_comment += 1
            if len(examples) < 5:
                examples.append(f"line {idx}: non-comment line changed: {a!r} -> {b!r}")
            continue
        if is_separator(a) != is_separator(b):
            separator_delta += 1
            if len(examples) < 5:
                examples.append(f"line {idx}: separator state changed: {a!r} -> {b!r}")
        if pa[0] != pb[0]:
            prefix_broken += 1
            if len(examples) < 5:
                examples.append(f"line {idx}: ';' prefix/spacing changed: {pa[0]!r} -> {pb[0]!r}")

    if changed_non_comment:
        problems.append(f"{changed_non_comment} section/key line(s) modified")
    if separator_delta:
        problems.append(f"{separator_delta} line(s) changed separator status")
    if prefix_broken:
        problems.append(f"{prefix_broken} comment line(s) lost their ';' prefix or spacing")
    problems.extend(examples)
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Translate the comments of OptiScaler.ini, leaving every "
                    "section header and key=value line byte-identical.")
    ap.add_argument("--ini", type=Path, required=True, help="upstream OptiScaler.ini")
    ap.add_argument("--dict", type=Path, default=DEFAULT_DICT,
                    help="comment dictionary (default: tools_cn/dict_ini.json)")
    ap.add_argument("--out", type=Path, help="output path (default: in place)")
    ap.add_argument("--check", action="store_true",
                    help="validate invariants only; do not write anything")
    ap.add_argument("--report", action="store_true",
                    help="print untranslated / rejected comment counts")
    ap.add_argument("--lint-dict", action="store_true",
                    help="verify that every dictionary key occurs in --ini")
    ap.add_argument("--force", action="store_true",
                    help="apply translations even when markers do not match")
    args = ap.parse_args()

    if not args.ini.exists():
        print(f"ERROR: ini not found: {args.ini}", file=sys.stderr)
        return 2
    table = load_dict(args.dict)

    text, had_bom, newline = read_ini(args.ini)
    in_lines = split_keep_endings(text)
    out_lines, stats = transform(in_lines, table, force=args.force)

    if args.lint_dict:
        present = {p[1] for p in (split_comment(l) for l in in_lines) if p}
        absent = [k for k in table if k not in present]
        print(f"dictionary keys: {len(table)}")
        print(f"keys not present in {args.ini.name}: {len(absent)}")
        for k in absent[:20]:
            print(f"  {k!r}")
        if absent:
            print("dict lint FAILED", file=sys.stderr)
            return 1
        print("dict lint OK")
        return 0

    problems = compare_guard(in_lines, out_lines)
    for p in problems:
        print(f"  GUARD: {p}", file=sys.stderr)

    if stats.rejected_lines:
        print(f"rejected translations: {stats.rejected}", file=sys.stderr)
        for ln, body, why in stats.rejected_lines[:20]:
            print(f"  line {ln}: {why}\n    {body!r}", file=sys.stderr)

    if args.report or args.check:
        print(f"comment lines        : {stats.comments}")
        print(f"separator lines      : {stats.separators}")
        print(f"translated           : {stats.translated}")
        print(f"already localized    : {stats.unchanged}")
        print(f"not in dictionary    : {stats.missing}")
        print(f"rejected by guard    : {stats.rejected}")

    if args.check:
        # Without --out there is nothing to compare against, and the strongest
        # assertion this script has - "the file on disk is byte-for-byte a fresh
        # translation" - would silently never run. That is how a --check step
        # can be green while the ini on disk is stale or half-translated, so a
        # missing comparison target is an error, not a warning.
        if args.out is None:
            print("ERROR: --check needs --out <path> to compare the on-disk file "
                  "against a fresh translation", file=sys.stderr)
            return 2

        failures = 0
        if problems:
            failures += 1
        if stats.rejected:
            failures += 1

        joined = newline.join(out_lines)
        encoded = joined.encode("utf-8")
        if encoded.startswith(b"\xef\xbb\xbf"):
            print("  CHECK: output must be UTF-8 without BOM", file=sys.stderr)
            failures += 1
        else:
            print("  CHECK: output is UTF-8 without BOM")
        if newline == "\r\n" and "\r\n" not in joined and len(out_lines) > 1:
            print("  CHECK: CRLF style was not preserved", file=sys.stderr)
            failures += 1
        print(f"  CHECK: newline style {newline!r}, lines {len(out_lines)}")

        if not args.out.exists():
            print(f"  CHECK: {args.out} does not exist, so the file that would be "
                  f"shipped cannot be compared against a fresh translation",
                  file=sys.stderr)
            failures += 1
        else:
            disk_text, disk_bom, _ = read_ini(args.out)
            if disk_bom:
                print(f"  CHECK: {args.out} has a BOM", file=sys.stderr)
                failures += 1
            if split_keep_endings(disk_text) != out_lines:
                print(f"  CHECK: {args.out} does not match a fresh translation",
                      file=sys.stderr)
                failures += 1
            else:
                print(f"  CHECK: {args.out} matches a fresh translation")

        if had_bom:
            print("  WARNING: input had a BOM, output keeps it")
        if failures:
            print("ini check FAILED", file=sys.stderr)
            return 1
        print("ini check OK")
        return 0

    target = args.out or args.ini
    target.parent.mkdir(parents=True, exist_ok=True)
    joined = newline.join(out_lines)
    if text.endswith("\n") and not joined.endswith("\n"):
        joined += "\n"
    target.write_text(joined, encoding="utf-8-sig" if had_bom else "utf-8",
                      newline="")
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{stats.translated}/{stats.comments} comments translated)")
    if problems:
        print("ERROR: guard violations, output should be reviewed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
