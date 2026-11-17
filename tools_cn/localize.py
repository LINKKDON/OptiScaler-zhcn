#!/usr/bin/env python3
"""Apply Chinese localization to a pristine OptiScaler checkout.

This is the "thin repo" variant of the old in-tree script: the upstream source
tree is NOT part of this repository, it is checked out at build time, so the
target checkout has to be passed explicitly with ``--repo``.

- Applies tools_cn/dict_v10.json to <repo>/OptiScaler/menu/*.cpp
- Embeds the CJK font: adds #include and the merge block to menu_common.cpp
- Idempotent: safe to run multiple times (second run reports 0 keys translated).

Usage:
    python tools_cn/localize.py --repo src --tools tools_cn
    python tools_cn/localize.py --check-dict --tools tools_cn
    python tools_cn/localize.py --repo src --tools tools_cn --dry-run

The string-substitution core (decode_c / encode_c / process_line / apply_dict /
FONT_MERGE_BLOCK / apply_font) is kept byte-for-byte identical to the version
that was validated against the upstream menus. Only the entry point changed.
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import argparse


def _force_utf8_stdio() -> None:
    """Make print() safe on hosts whose stdio defaults to a legacy code page.

    Windows runners hand Python a cp1252 stdout, but several diagnostics below
    print dictionary keys and Chinese values. Without this, a *failing* check
    dies with UnicodeEncodeError and hides the real message.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_force_utf8_stdio()

REPO = Path(".")
MENU = Path(".")
DICT_PATH = Path("dict_v10.json")
FONT_HEADER = "font/CJK_Compressed.h"

DICT = {}


def decode_c(s: str) -> str:
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c); i += 1; continue
        i += 1
        if i >= n:
            out.append("\\"); break
        e = s[i]; i += 1
        m = {"n": "\n", "r": "\r", "t": "\t", "a": "\a", "b": "\b",
             "f": "\f", "v": "\v", "0": "\0"}.get(e)
        if m:
            out.append(m)
        elif e in "\\\"'?":
            out.append(e)
        elif e == "x":
            h = s[i:i + 2]; out.append(chr(int(h, 16)) if h else "x"); i += len(h)
        elif e == "u":
            h = s[i:i + 4]; out.append(chr(int(h, 16)) if len(h) == 4 else "u"); i += len(h)
        elif e == "U":
            h = s[i:i + 8]; out.append(chr(int(h, 16)) if len(h) == 8 else "U"); i += len(h)
        else:
            out.append(e)
    return "".join(out)


def encode_c(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def process_line(line: str, in_block: bool):
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if in_block:
            end = line.find("*/", i)
            if end == -1:
                out.append(line[i:]); return "".join(out), True
            out.append(line[i:end + 2]); i = end + 2; in_block = False; continue
        if line.startswith("//", i):
            out.append(line[i:]); return "".join(out), False
        if c == "/" and i + 1 < n and line[i + 1] == "*":
            end = line.find("*/", i + 2)
            if end == -1:
                out.append(line[i:]); return "".join(out), True
            out.append(line[i:end + 2]); i = end + 2; continue
        if c == '"':
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2; continue
                if line[j] == '"':
                    j += 1; break
                j += 1
            value = decode_c(line[i + 1:j - 1])
            if value in DICT:
                out.append('"' + encode_c(DICT[value]) + '"')
            else:
                out.append(line[i:j])
            i = j; continue
        out.append(c); i += 1
    return "".join(out), in_block


def apply_dict(path: Path) -> int:
    data = path.read_bytes()
    had_bom = data.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in data
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    in_block = False
    for li, line in enumerate(lines):
        lines[li], in_block = process_line(line, in_block)
    new_text = "\n".join(lines)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    # count replacements
    cnt = sum(
        max(0, text.count(f'"{encode_c(k)}"') - new_text.count(f'"{encode_c(k)}"'))
        for k in DICT
    )
    path.write_text(new_text, encoding="utf-8-sig" if had_bom else "utf-8",
                    newline="\r\n" if crlf else "\n")
    return cnt


FONT_MERGE_BLOCK = """
    // [CN] Merge the embedded CJK subset font so the Chinese UI renders correctly.
    {
        ImFontAtlas* atlas = io.Fonts;

        // Ensure a base font exists even when the HQ font is disabled.
        if (atlas->Fonts.empty())
            io.FontDefault = atlas->AddFontDefault();

        ImFontConfig cjkConfig;
        cjkConfig.MergeMode = true;
        cjkConfig.FontNo = 0;
        cjkConfig.OversampleH = 1;
        cjkConfig.OversampleV = 1;

        static const ImWchar cjkGlyphRanges[] = {
            0x0020, 0x00FF, // Basic Latin + Latin-1 Supplement
            0x2000, 0x2BFF, // Punctuation, symbols, arrows, math
            0x3000, 0x303F, // CJK Symbols and Punctuation
            0xFF00, 0xFFEF, // Halfwidth and Fullwidth Forms
            0x4E00, 0x9FAF, // CJK Unified Ideographs
            0,
        };

        atlas->AddFontFromMemoryCompressedTTF(cjk_compressed_data, cjk_compressed_size, fontSize, &cjkConfig,
                                              cjkGlyphRanges);
    }
"""


class LocalizationError(RuntimeError):
    """An upstream anchor the localization relies on has drifted or is gone."""


FONT_INCLUDE_ANCHOR = '#include "font/Hack_Compressed.h"'
FONT_INCLUDE_LINE = '#include "font/CJK_Compressed.h"'
FONT_BLOCK_MARKER = "[CN] Merge the embedded CJK subset font"
FONT_BLOCK_ANCHOR = "    if (!Config::Instance()->OverlayMenu.value_or_default())"


def _count(text: str, needle: str) -> int:
    return text.count(needle)


DIRECTIVE_RE = re.compile(r"([A-Za-z_]+)(.*)")


def _directive(line: str):
    """Split one preprocessor line into (keyword, condition)."""
    body = line[1:].strip()
    m = DIRECTIVE_RE.match(body)
    if not m:
        return "", ""
    keyword, condition = m.group(1), m.group(2)
    condition = condition.split("//", 1)[0]
    while "/*" in condition:
        head, _, rest = condition.partition("/*")
        _, _, tail = rest.partition("*/")
        condition = head + " " + tail
    return keyword, condition.strip()


def strip_noncode(text: str, keep_line_comments: bool = False) -> str:
    """Blank out C/C++ comments and ``#if 0`` regions, keeping every offset.

    Returns a string of exactly ``len(text)`` characters: comments and disabled
    preprocessor branches become spaces, newlines are left untouched, and real
    code (including the contents of string and character literals) is copied
    verbatim. Because the length and the newlines survive, an offset found in the
    stripped view is also valid in the original text - that is what lets
    :func:`apply_font` count anchors on the code view and still splice the
    original string.

    Why this exists: plain ``str.count()`` cannot tell code from a comment. When
    upstream wraps the font-loading anchor in ``/* ... */``, the naive count is
    still 1, the merge block is spliced into the comment, ``cjk_compressed_data``
    ends up declared but never referenced, and cl.exe compiles it happily - a DLL
    advertised as localized with no Chinese glyphs, and a green CI run. Counting
    on the stripped view makes that case a hard error.

    ``keep_line_comments`` exists for one caller: the merge-block marker is
    itself a ``//`` comment by design, so it can never survive the full strip.
    With ``keep_line_comments=True`` only block comments and ``#if 0`` regions
    are blanked, which answers the question that actually matters for it - "was
    this marker swallowed by a surrounding ``/* */`` or a disabled branch?" -
    while leaving the marker line itself readable.

    Handled lexical states: ``//`` to end of line, ``/* */`` across lines, ``"``
    and ``'`` literals with backslash escapes (so ``"http://host"`` and ``"/*"``
    are not mistaken for comments), C++ raw strings (``R"delim(...)delim"``),
    and ``#if 0`` / ``#if 1`` / ``#else`` / ``#elif`` / ``#endif`` nesting.
    ``#if 0`` regions are stripped only when the ``0`` is the whole condition;
    anything else is treated as live code, because guessing wrong in that
    direction would hide real code from the anchor search.
    """
    out = list(text)
    n = len(text)
    i = 0
    in_block = False
    line_start = True
    # One frame per open #if: parent_dead is whether the enclosing region is
    # already dead, branch_dead is whether the branch we are in is #if 0.
    frames = []

    def dead() -> bool:
        return bool(frames) and (frames[-1]["parent_dead"] or frames[-1]["branch_dead"])

    def blank(start: int, stop: int) -> None:
        for k in range(start, min(stop, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = text[i]

        if c == "\n":
            i += 1
            line_start = True
            continue

        if in_block:
            if text.startswith("*/", i):
                blank(i, i + 2)
                i += 2
                in_block = False
            else:
                blank(i, i + 1)
                i += 1
            line_start = False
            continue

        if line_start and c == "#":
            eol = text.find("\n", i)
            if eol == -1:
                eol = n
            keyword, condition = _directive(text[i:eol])
            if keyword in ("if", "ifdef", "ifndef"):
                frames.append({"parent_dead": dead(),
                               "branch_dead": keyword == "if" and condition == "0"})
            elif keyword == "else":
                if frames:
                    frames[-1]["branch_dead"] = False
            elif keyword == "elif":
                if frames:
                    frames[-1]["branch_dead"] = condition == "0"
            elif keyword == "endif":
                if frames:
                    frames.pop()
            if dead():
                blank(i, eol)
            i = eol
            continue

        if dead():
            blank(i, i + 1)
            i += 1
            line_start = False
            continue

        if text.startswith("//", i):
            eol = text.find("\n", i)
            if eol == -1:
                eol = n
            if not keep_line_comments:
                blank(i, eol)
            i = eol
            line_start = False
            continue

        if text.startswith("/*", i):
            blank(i, i + 2)
            i += 2
            in_block = True
            line_start = False
            continue

        if (c == "R" and i + 1 < n and text[i + 1] == '"'
                and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"))):
            opening = text.find("(", i + 2)
            if opening != -1 and opening - (i + 2) <= 16:
                delimiter = text[i + 2:opening]
                terminator = ")" + delimiter + '"'
                end = text.find(terminator, opening + 1)
                if end != -1:
                    i = end + len(terminator)
                    line_start = False
                    continue

        if c in ('"', "'"):
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == c:
                    j += 1
                    break
                if text[j] == "\n":
                    break
                j += 1
            i = j
            line_start = False
            continue

        if not c.isspace():
            line_start = False
        i += 1

    return "".join(out)


def apply_font() -> str:
    """Integrate the CJK font into menu_common.cpp.

    Returns ``"applied"`` when the include and the merge block were just
    inserted, ``"unchanged"`` when both were already present.

    Raises :class:`LocalizationError` when an anchor is missing, when an anchor
    is ambiguous (more than one match) or when exactly one of the two pieces is
    already present. All three cases used to be silent no-ops: the old version
    set ``changed = True`` even when ``str.replace()`` had nothing to replace,
    and it skipped the merge block entirely when its anchor had drifted. That
    produced a DLL advertised as localized but compiled without the Chinese
    font, with a green CI run.
    """
    p = MENU / "menu_common.cpp"
    text = p.read_text(encoding="utf-8")

    # Anchors are searched in the code view, never in the raw text: a comment or
    # an #if 0 branch can contain the anchor text while being dead code, and
    # splicing the merge block there compiles fine but ships no Chinese glyphs.
    # The marker is a // comment by design, so it is checked with line comments
    # kept - only a surrounding /* */ or a disabled branch can hide it.
    code = strip_noncode(text)
    code_with_line_comments = strip_noncode(text, keep_line_comments=True)

    has_inc = FONT_INCLUDE_LINE in code
    has_block = FONT_BLOCK_MARKER in code_with_line_comments

    if has_inc and has_block:
        return "unchanged"
    if has_inc != has_block:
        missing = "merge block" if has_inc else 'the #include "font/CJK_Compressed.h" line'
        raise LocalizationError(
            f"{p} is in a half-injected state: {missing} is missing while the "
            f"other half is present. Refusing to guess; restore the pristine "
            f"file (or delete both halves) and re-run.")

    # Neither half is present, so both anchors have to be reachable.
    n_inc = _count(code, FONT_INCLUDE_ANCHOR)
    if n_inc == 0:
        raise LocalizationError(
            f'{p}: anchor {FONT_INCLUDE_ANCHOR!r} not found in code (comments and '
            f'#if 0 regions are ignored). Upstream renamed or moved it; without '
            f'it the CJK header is never included and the build would silently '
            f'ship a DLL without Chinese glyphs.')
    if n_inc > 1:
        raise LocalizationError(
            f'{p}: anchor {FONT_INCLUDE_ANCHOR!r} occurs {n_inc} times, the '
            f'injection point is ambiguous.')

    n_block = _count(code, FONT_BLOCK_ANCHOR)
    if n_block == 0:
        raise LocalizationError(
            f'{p}: anchor {FONT_BLOCK_ANCHOR!r} not found in code (comments and '
            f'#if 0 regions are ignored). Upstream changed the font-loading '
            f'block, or commented it out; either way the CJK font would never be '
            f'merged into the ImGui atlas.')
    if n_block > 1:
        raise LocalizationError(
            f'{p}: anchor {FONT_BLOCK_ANCHOR!r} occurs {n_block} times, the '
            f'injection point is ambiguous.')

    # 1. Add #include
    text = text.replace(FONT_INCLUDE_ANCHOR,
                        FONT_INCLUDE_ANCHOR + "\n" + FONT_INCLUDE_LINE, 1)

    # 2. Add merge block after the font-loading if-block
    text = text.replace(FONT_BLOCK_ANCHOR,
                        FONT_MERGE_BLOCK.strip("\n") + "\n\n" + FONT_BLOCK_ANCHOR, 1)

    # 3. Prove the block landed in live code, not inside a comment.
    after = strip_noncode(text, keep_line_comments=True)
    if _count(after, FONT_BLOCK_MARKER) != 1:
        raise LocalizationError(
            f"{p}: the merge block landed inside a comment; the anchor was "
            f"commented out upstream. The block would be dead code and the DLL "
            f"would ship without Chinese glyphs, so this is fatal.")
    if _count(strip_noncode(text), "atlas->AddFontFromMemoryCompressedTTF(") < 1:
        raise LocalizationError(
            f"{p}: the injected merge block is not reachable as code; the font "
            f"would never be loaded into the atlas.")

    # preserve line endings
    data = p.read_bytes()
    crlf = b"\r\n" in data
    p.write_text(text, encoding="utf-8", newline="\r\n" if crlf else "\n")
    return "applied"


def verify_overlay(menu: Path, require_font_header: bool = True) -> int:
    """Re-read the checkout and prove the localization is really in place.

    Deliberately independent of :func:`apply_font`'s return value: it parses the
    files back from disk, so a no-op injection cannot pass. Returns 0 / 1.
    """
    problems = []

    cpp = menu / "menu_common.cpp"
    if not cpp.is_file():
        _error(f"{cpp} is missing; there is nothing to localize.")
        return 1
    try:
        text = cpp.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        _error(f"{cpp} is not valid UTF-8 after injection: {exc}")
        return 1

    # Everything below is counted in the code view. A marker that only exists
    # inside a comment proves nothing: the merge block would be dead code. The
    # marker is itself a // comment, so it is checked with line comments kept.
    code = strip_noncode(text)
    code_with_line_comments = strip_noncode(text, keep_line_comments=True)

    n_inc = _count(code, FONT_INCLUDE_LINE)
    if n_inc != 1:
        problems.append(f"{cpp}: expected exactly 1 {FONT_INCLUDE_LINE!r} in code "
                        f"(comments ignored), found {n_inc}")
    n_marker = _count(code_with_line_comments, FONT_BLOCK_MARKER)
    if n_marker != 1:
        problems.append(f"{cpp}: expected exactly 1 {FONT_BLOCK_MARKER!r} marker "
                        f"outside /* */ and #if 0, found {n_marker}")
    if "cjk_compressed_data" not in code:
        problems.append(f"{cpp}: the merge block does not reference "
                        f"cjk_compressed_data outside comments")
    if "cjk_compressed_size" not in code:
        problems.append(f"{cpp}: the merge block does not reference "
                        f"cjk_compressed_size outside comments")
    if _count(code, "atlas->AddFontFromMemoryCompressedTTF(") < 1:
        problems.append(f"{cpp}: no live atlas->AddFontFromMemoryCompressedTTF("
                        f" call; the CJK font is never merged into the atlas")

    if not text.isascii():
        # Informational: the translations themselves are UTF-8, so this is the
        # proof that the dictionary part ran too.
        print(f"  menu_common.cpp contains {sum(1 for c in text if ord(c) > 127)} "
              f"non-ASCII character(s)")

    if require_font_header:
        problems.extend(_check_font_header(menu / "font" / "CJK_Compressed.h"))
    else:
        header = menu / "font" / "CJK_Compressed.h"
        if not header.is_file():
            print(f"  note: {header} absent, skipped the font header assertions "
                  f"(nothing is written in this mode, so no build can consume it)")

    for line in problems:
        _error(line)
    if problems:
        return 1
    print("CJK font integration verified in menu_common.cpp")
    return 0


def _check_font_header(header: Path) -> list:
    """Check that the generated header exists and is self-consistent."""
    if not header.is_file():
        return [f"{header} is missing; build_font.py did not produce it before "
                f"localize.py ran"]
    raw = header.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return [f"{header} has a UTF-8 BOM"]
    text = raw.decode("utf-8", errors="replace")
    problems = []
    if "cjk_compressed_data" not in text:
        problems.append(f"{header} does not define cjk_compressed_data")
    size_match = re.search(r"cjk_compressed_size\s*=\s*(\d+)", text)
    array_match = re.search(r"cjk_compressed_data\s*\[\s*(\d+)\s*\]", text)
    if not size_match:
        problems.append(f"{header}: cjk_compressed_size declaration not found")
    if not array_match:
        problems.append(f"{header}: cjk_compressed_data[N] declaration not found")
    if size_match and array_match and size_match.group(1) != array_match.group(1):
        problems.append(f"{header}: cjk_compressed_size ({size_match.group(1)}) does "
                        f"not match cjk_compressed_data[{array_match.group(1)}]")
    return problems


def _error(message: str) -> None:
    """Report a hard failure both to stderr and as a GitHub Actions annotation."""
    print(f"::error::{message}")
    print(f"ERROR: {message}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# dictionary validation (used by .github/workflows/ci-check.yml)
# --------------------------------------------------------------------------- #
# printf / std::format style conversion specifiers. "%%" is a literal percent
# sign, not a conversion, and is therefore not counted.
CONV_RE = re.compile(r"%(?:%|[-+ 0#']*[0-9]*(?:\.[0-9]+)?(?:hh|h|ll|l|j|z|t|L)?[diouxXeEfFgGaAcspn])")


def _conversions(text: str) -> list:
    return [m.group(0) for m in CONV_RE.finditer(text) if m.group(0) != "%%"]


def check_dict(dict_path: Path, strict_case_dup: bool = False) -> int:
    """Validate dict_v10.json.

    Hard failures (exit 1):
      1. the file is not valid JSON / not an object / empty key / empty value
      2. exact duplicate keys in the file
      3. keys containing "##" must keep the same "##<id>" suffix in the value
      4. the number of printf conversions must match the key
      5. the number of {} placeholders must match the key (std::format)
    Advisory only: keys that differ from another key by case alone. dict_v10.json
    intentionally contains 29 such pairs (upstream has both "ON"/"On" and
    "OFF"/"Off" spellings and they are distinct strings in the C++ source), so
    failing on them would reject a valid dictionary. Pass --strict-case-dup to
    turn them into failures.
    """
    if not dict_path.exists():
        print(f"ERROR: dictionary not found: {dict_path}", file=sys.stderr)
        return 1
    raw = dict_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        print(f"ERROR: {dict_path} has a UTF-8 BOM, expected none", file=sys.stderr)
        return 1
    if b"\r\n" in raw:
        print(f"ERROR: {dict_path} uses CRLF line endings, expected LF", file=sys.stderr)
        return 1

    dups = []

    def hook(pairs):
        seen = set()
        for k, v in pairs:
            if k in seen:
                dups.append(k)
            seen.add(k)
        return dict(pairs)

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=hook)
    except (UnicodeDecodeError, ValueError) as exc:
        print(f"ERROR: {dict_path} is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print(f"ERROR: {dict_path} must contain a JSON object", file=sys.stderr)
        return 1

    print(f"dictionary: {dict_path}")
    print(f"  entries: {len(data)}")

    failures = 0

    if dups:
        failures += 1
        print(f"  FAIL exact duplicate keys ({len(dups)}): {dups}", file=sys.stderr)

    empty = [k for k, v in data.items() if not k or not v or not str(v).strip()]
    if empty:
        failures += 1
        print(f"  FAIL empty key/value ({len(empty)}): {empty[:10]}", file=sys.stderr)

    bad_ids = []
    for k, v in data.items():
        if "##" in k:
            suffix = k[k.index("##"):].rstrip()
            if not str(v).rstrip().endswith(suffix):
                bad_ids.append((k, v, suffix))
    if bad_ids:
        failures += 1
        print(f"  FAIL ## id-suffix not preserved ({len(bad_ids)}):", file=sys.stderr)
        for k, v, s in bad_ids[:10]:
            print(f"        {k!r} -> {v!r} lacks suffix {s!r}", file=sys.stderr)

    bad_conv = [(k, v) for k, v in data.items() if _conversions(k) != _conversions(str(v))]
    if bad_conv:
        failures += 1
        print(f"  FAIL printf conversion mismatch ({len(bad_conv)}):", file=sys.stderr)
        for k, v in bad_conv[:10]:
            print(f"        {k!r} {_conversions(k)} -> {v!r} {_conversions(str(v))}", file=sys.stderr)

    bad_brace = [(k, v) for k, v in data.items()
                 if k.count("{") != str(v).count("{") or k.count("}") != str(v).count("}")]
    if bad_brace:
        failures += 1
        print(f"  FAIL brace placeholder mismatch ({len(bad_brace)}):", file=sys.stderr)
        for k, v in bad_brace[:10]:
            print(f"        {k!r} -> {v!r}", file=sys.stderr)

    folded = {}
    for k in data:
        folded.setdefault(k.casefold(), []).append(k)
    case_dups = [v for v in folded.values() if len(v) > 1]
    if case_dups:
        level = "FAIL" if strict_case_dup else "WARNING"
        stream = sys.stderr if strict_case_dup else sys.stdout
        if strict_case_dup:
            failures += 1
        print(f"  {level} case-only duplicate keys ({len(case_dups)} groups)", file=stream)
        for grp in case_dups[:10]:
            print(f"        {grp}", file=stream)
        if not strict_case_dup:
            print("        (expected: dict_v10.json keeps upstream's ON/On and OFF/Off "
                  "spellings; use --strict-case-dup to treat this as an error)", file=stream)

    if failures:
        print(f"dictionary check FAILED ({failures} problem group(s))", file=sys.stderr)
        return 1
    print("dictionary check OK")
    return 0


def load_dict(path: Path) -> None:
    global DICT
    DICT = json.loads(path.read_text(encoding="utf-8"))
    assert all(v for v in DICT.values()), "empty translation value"


# --------------------------------------------------------------------------- #
# coverage reporting (used by the build workflows and by ci-check.yml)
# --------------------------------------------------------------------------- #
# Why this exists: the dictionary can lose touch with upstream without anything
# failing. When upstream rewords or deletes a menu string, the corresponding
# dict entry silently becomes a dead key, the menu item falls back to English,
# and every check in this repository stays green because --check-dict only
# validates the dictionary against itself. Measured on 2026-11-16: master had
# 1223 live keys against a 11-13 snapshot's 1248 - 25 keys gone in three days,
# 0 added, while upstream grew by ~90 new literals.
#
# `translated` deliberately reuses apply_dict()'s counting recipe (exact
# `"<escaped>"` byte match through encode_c) so the number here is the same one
# `Total keys translated:` reports, and so it is comparable with the baseline.
#
# IMPORTANT - this measures the *pristine* tree, which is why the workflow runs
# it before the injection step, not after. Injection replaces every key literal
# with its translation, so a byte scan for the keys finds nothing afterwards;
# counting the translations instead is not comparable either, because 46 values
# are shared by two keys and the merge block adds literals of its own. The
# quantity this reports is a property of (dictionary, upstream sources), which
# is exactly what coverage-baseline.json records, so both sides have to be
# measured on unmodified sources.
GUID_RE = re.compile(r"^\{\{[^}]*\}\}$")

# Percentage points of coverage that may vanish before a ::warning:: is raised
# while the absolute key drop is still inside the --max-drop budget. See the
# percent_delta branch in run_coverage() for why this is not a hard gate.
PERCENT_WARN_DROP = 5.0


def _source_literals(path: Path) -> list:
    """Decode the string literals of one C++ file, skipping comments.

    Mirrors process_line()'s scanning rules, with one difference that matters
    for counting: the block-comment state is carried across lines. process_line()
    is called per line by apply_dict() and cannot carry it, so a literal that
    sits on the closing line of a block comment is rewritten there but not
    counted here. That only affects `total`, never which strings get translated.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    out = []
    in_block = False
    for line in text.splitlines():
        i, n = 0, len(line)
        while i < n:
            if in_block:
                end = line.find("*/", i)
                if end == -1:
                    i = n
                    break
                i = end + 2
                in_block = False
                continue
            if line.startswith("//", i):
                break
            c = line[i]
            if c == "/" and i + 1 < n and line[i + 1] == "*":
                end = line.find("*/", i + 2)
                if end == -1:
                    in_block = True
                    i = n
                    break
                i = end + 2
                continue
            if c == '"':
                j = i + 1
                while j < n:
                    if line[j] == "\\":
                        j += 2
                        continue
                    if line[j] == '"':
                        j += 1
                        break
                    j += 1
                out.append(decode_c(line[i + 1:j - 1]))
                i = j
                continue
            i += 1
    return out


def _is_countable_literal(value: str) -> bool:
    """A literal that a translator could plausibly own.

    len >= 3 drops "" / "x" / "%d"; requiring a letter drops "%s %u.%u.%u" and
    "{}X"; GUID placeholders like {{4d36e968-...}} are registry keys, not UI
    text. These three rules are what reproduce the numbers recorded in
    coverage-baseline.json - change them and the baseline has to be re-recorded.
    """
    return (len(value) >= 3
            and any(ch.isalpha() for ch in value)
            and not GUID_RE.match(value))


def measure_coverage(menu: Path, dict_path: Path) -> dict:
    """Return the coverage numbers for one menu directory. Read-only.

    Must be called on a pristine (not yet localized) checkout - see the note
    above GUID_RE.
    """
    table = json.loads(dict_path.read_text(encoding="utf-8"))

    literals = set()
    blobs = []
    for path in sorted(menu.glob("*.cpp")):
        literals.update(_source_literals(path))
        blobs.append(path.read_text(encoding="utf-8", errors="replace"))
    blob = "".join(blobs)

    countable = {v for v in literals if _is_countable_literal(v)}
    covered = sum(1 for key in table if f'"{encode_c(key)}"' in blob)

    total = len(countable)
    percent = (100.0 * covered / total) if total else 0.0
    return {"translated": covered, "total": total, "percent": round(percent, 1),
            "dictionary_entries": len(table),
            "files": len(blobs)}


def run_coverage(menu: Path, dict_path: Path, baseline_path, json_path,
                 max_drop: int) -> int:
    """Print one machine-readable coverage line and enforce the drop budget.

    Exit codes: 0 = fine (possibly with a ::warning::), 1 = the drop budget was
    exceeded, 2 = the baseline or dictionary could not be read.
    """
    try:
        data = measure_coverage(menu, dict_path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: could not measure the coverage: {exc}", file=sys.stderr)
        return 2

    baseline = data["translated"]
    upstream_sha = ""
    recorded_baseline = None
    if baseline_path is None:
        # Without a baseline the delta is 0 by construction, so say so out loud:
        # a silent "delta=0" is exactly the kind of quiet pass this repository is
        # trying not to ship. The build workflows always pass --baseline.
        print("  note: no --baseline given, so delta is 0 by construction and no "
              "drop can be detected")
    if baseline_path is not None:
        try:
            recorded = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"ERROR: could not read the baseline {baseline_path}: {exc}",
                  file=sys.stderr)
            return 2
        if not isinstance(recorded, dict) or "translated" not in recorded:
            print(f"ERROR: {baseline_path} is not a coverage baseline (no "
                  f"'translated' field)", file=sys.stderr)
            return 2
        recorded_baseline = recorded
        baseline = int(recorded["translated"])
        upstream_sha = str(recorded.get("upstream_sha", ""))

    delta = data["translated"] - baseline
    baseline_total = data["total"]
    if isinstance(recorded_baseline, dict) and "total" in recorded_baseline:
        try:
            baseline_total = int(recorded_baseline["total"])
        except (TypeError, ValueError):
            baseline_total = data["total"]
    baseline_percent = (round(100.0 * baseline / baseline_total, 1)
                        if baseline_total else 0.0)
    percent_delta = round(data["percent"] - baseline_percent, 1)

    print(f"coverage: translated={data['translated']} total={data['total']} "
          f"percent={data['percent']} baseline={baseline} delta={delta} "
          f"baseline_percent={baseline_percent} percent_delta={percent_delta}")
    print(f"  dictionary entries: {data['dictionary_entries']}, "
          f"menu sources scanned: {data['files']}")
    if upstream_sha:
        print(f"  baseline recorded against upstream {upstream_sha}")

    # baseline_total is the `total` that was recorded alongside `translated` in
    # the baseline file. It is what makes percent_delta meaningful: without it a
    # run that gains 400 untranslated upstream strings looks identical to a run
    # that gained nothing, because `translated` does not move.
    payload = dict(data, baseline=baseline, delta=delta,
                   baseline_percent=baseline_percent,
                   baseline_total=baseline_total,
                   percent_delta=percent_delta,
                   upstream_sha=upstream_sha, max_drop=max_drop)
    if json_path is not None:
        out = Path(json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8", newline="\n")
        print(f"  wrote {out}")

    if delta < -max_drop:
        _error(f"translation coverage dropped by {-delta} keys (baseline "
               f"{baseline}, actual {data['translated']}); upstream reworded the "
               f"UI. Re-record tools_cn/coverage-baseline.json or restore the "
               f"dictionary.")
        return 1
    if delta < 0:
        print(f"::warning::translation coverage dropped by {-delta} keys "
              f"(baseline {baseline}, actual {data['translated']}); within the "
              f"{max_drop}-key budget, but upstream reworded the UI. Re-record "
              f"tools_cn/coverage-baseline.json when the loss is confirmed.")
    elif percent_delta < -PERCENT_WARN_DROP:
        # A percent drop with delta >= 0 means `total` grew: upstream added UI
        # strings that the dictionary does not cover yet. That is a normal kind
        # of drift, so it is only a warning - never a failure. Without this line
        # the gate would be blind to "upstream added 100 strings, none of them
        # translated", which leaves `translated` unchanged.
        added = data["total"] - baseline_total
        print(f"::warning::translation coverage percent dropped from "
              f"{baseline_percent}% to {data['percent']}% (baseline total "
              f"{baseline_total}, actual total {data['total']}); upstream added "
              f"{added} untranslated string(s). Extend dict_v10.json or re-record "
              f"tools_cn/coverage-baseline.json.")
    return 0


def main() -> int:
    global REPO, MENU, DICT_PATH

    ap = argparse.ArgumentParser(
        description="Inject the Chinese menu translations and the embedded CJK "
                    "font into a pristine OptiScaler checkout.")
    ap.add_argument("--repo", type=Path,
                    help="root of the upstream OptiScaler checkout (the directory "
                         "that contains OptiScaler/menu)")
    ap.add_argument("--tools", type=Path, default=Path(__file__).resolve().parent,
                    help="directory holding dict_v10.json (default: this script's dir)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without touching the checkout")
    ap.add_argument("--check-dict", action="store_true",
                    help="only validate dict_v10.json, do not touch any source file")
    ap.add_argument("--strict-case-dup", action="store_true",
                    help="with --check-dict: treat case-only duplicate keys as errors")
    ap.add_argument("--verify", action="store_true",
                    help="only re-check that the checkout carries the localization "
                         "(no file is written); exits non-zero when the include, the "
                         "merge block or the font header is missing")
    ap.add_argument("--coverage", action="store_true",
                    help="only measure how much of the upstream menu the dictionary "
                         "still covers (no file is written); exits non-zero when the "
                         "coverage dropped by more than --max-drop keys")
    ap.add_argument("--coverage-json", type=Path,
                    help="with --coverage: also write the numbers as JSON")
    ap.add_argument("--baseline", type=Path,
                    help="with --coverage: coverage-baseline.json to compare against")
    ap.add_argument("--max-drop", type=int, default=20,
                    help="with --coverage: how many keys may be lost before this "
                         "becomes a hard failure (default: 20)")
    args = ap.parse_args()

    tools = args.tools.resolve()
    DICT_PATH = tools / "dict_v10.json"

    if args.check_dict:
        return check_dict(DICT_PATH, args.strict_case_dup)

    if args.repo is None:
        ap.error("--repo is required (root of the upstream OptiScaler checkout)")

    REPO = args.repo.resolve()
    if not REPO.is_dir():
        print(f"ERROR: --repo does not exist or is not a directory: {REPO}", file=sys.stderr)
        return 2
    MENU = REPO / "OptiScaler" / "menu"
    if not MENU.is_dir():
        print(f"ERROR: {MENU} not found - is --repo the root of an OptiScaler checkout?",
              file=sys.stderr)
        return 2

    if args.coverage:
        # Read-only, like --verify: it reports, it never rewrites the tree.
        print(f"repository: {REPO}")
        return run_coverage(MENU, DICT_PATH, args.baseline, args.coverage_json,
                            args.max_drop)

    if args.verify:
        # Read-only mode: the dictionary is irrelevant, only the injected state
        # and the generated font header matter.
        print(f"repository: {REPO}")
        return verify_overlay(MENU, require_font_header=True)

    if not DICT_PATH.exists():
        print(f"ERROR: dictionary not found: {DICT_PATH}", file=sys.stderr)
        return 2

    load_dict(DICT_PATH)
    print(f"repository: {REPO}")
    print(f"dictionary: {DICT_PATH} ({len(DICT)} entries)")

    tmp_root = None
    if args.dry_run:
        tmp_root = Path(tempfile.mkdtemp(prefix="localize-dryrun-"))
        shutil.copytree(MENU, tmp_root / "menu")
        MENU = tmp_root / "menu"
        print(f"dry-run: working on a temporary copy ({MENU})")

    try:
        total = 0
        for f in sorted(MENU.glob("*.cpp")):
            n = apply_dict(f)
            total += n
            print(f"{f.name}: {n} keys translated")
        print(f"Total keys translated: {total}")

        try:
            state = apply_font()
        except LocalizationError as exc:
            _error(str(exc))
            return 1
        if state == "applied":
            print("CJK font integration applied to menu_common.cpp")
        else:
            print("CJK font integration already present")

        # Post-condition check, parsed back from disk. It does not trust the
        # return value above: an injection that silently did nothing has to
        # fail here rather than ship a DLL that claims to be localized.
        # A dry run works on a throwaway copy, so the font header assertions are
        # relaxed there (nothing is compiled from that copy).
        if verify_overlay(MENU, require_font_header=not args.dry_run) != 0:
            _error("the checkout does not carry the localization that was just "
                   "applied; refusing to report success")
            return 1
    finally:
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)

    if args.dry_run:
        print("dry-run: no source file was modified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
