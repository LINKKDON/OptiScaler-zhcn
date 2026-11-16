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


def apply_font() -> bool:
    """Integrate the CJK font into menu_common.cpp. Returns True if changed."""
    p = MENU / "menu_common.cpp"
    text = p.read_text(encoding="utf-8")
    changed = False

    # 1. Add #include (idempotent)
    inc = '#include "font/CJK_Compressed.h"'
    if inc not in text:
        text = text.replace('#include "font/Hack_Compressed.h"',
                            '#include "font/Hack_Compressed.h"\n' + inc, 1)
        changed = True

    # 2. Add merge block after the font-loading if-block (idempotent)
    if "[CN] Merge the embedded CJK subset font" not in text:
        anchor = "    if (!Config::Instance()->OverlayMenu.value_or_default())"
        if anchor in text:
            text = text.replace(anchor, FONT_MERGE_BLOCK.strip("\n") + "\n\n" + anchor, 1)
            changed = True

    if changed:
        # preserve line endings
        data = p.read_bytes()
        crlf = b"\r\n" in data
        p.write_text(text, encoding="utf-8", newline="\r\n" if crlf else "\n")
    return changed


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

        if apply_font():
            print("CJK font integration applied to menu_common.cpp")
        else:
            print("CJK font integration already present")
    finally:
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)

    # The font header is produced by tools_cn/build_font.py, which the build
    # workflow runs *before* this script. Missing header is therefore only a
    # warning here (in the old in-tree repo it was effectively a hard error).
    if not (MENU / "font" / "CJK_Compressed.h").exists():
        print("WARNING: OptiScaler/menu/font/CJK_Compressed.h missing; "
              "it will be generated by build_font.py", file=sys.stderr)
    if args.dry_run:
        print("dry-run: no source file was modified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
