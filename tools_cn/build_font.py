#!/usr/bin/env python3
"""Regenerate the embedded CJK font subset for the Chinese UI.

Fixes the bug where the subset was built from the old ``dict.json`` while
``localize.py`` substitutes using ``dict_v10.json``, leaving 49 characters
without glyphs (Reprojection / Depth cutoff etc. rendered blank).

Pipeline (pure Python, no Windows-only tooling required):
  1. collect every character that can end up in the UI:
       - all values of the dictionary (default tools_cn/dict_v10.json)
       - every CJK/punctuation char already present in OptiScaler/menu/*.cpp
       - printable ASCII 0x20..0x7E and the extra PUNCT set
  2. subset the source TrueType/TrueType-Collection to those characters
  3. verify coverage - a missing glyph is a hard failure (missing glyphs are
     exactly the bug this script exists to prevent)
  4. stb_compress the subset, verify the round-trip, emit CJK_Compressed.h

Usage:
    python tools_cn/build_font.py --out src/OptiScaler/menu/font
    python tools_cn/build_font.py --selftest
    python tools_cn/build_font.py --check --out src/OptiScaler/menu/font
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import tempfile
from pathlib import Path


def _force_utf8_stdio() -> None:
    """Make print() safe on hosts whose stdio defaults to a legacy code page.

    The missing-glyph report below prints the CJK characters themselves, so on
    a cp1252 console it would crash exactly when it has something important to
    say. Reconfigure once at import time.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_force_utf8_stdio()

HERE = Path(__file__).resolve().parent

MENU: Path | None = None
FONT_HEADER: Path | None = None

DEFAULT_SOURCE_WINDOWS = Path(r"C:\Windows\Fonts\msyh.ttc")
BUNDLED_SOURCE = HERE / "msyh_cjk.ttf"
DEFAULT_DICT = HERE / "dict_v10.json"

# Extra punctuation that appears in the UI but may not be reachable from the dict.
PUNCT = "，。！？：；（）【】《》〈〉「」『』…—–·、％℃×÷＝＋－＊／＃＠＆"

CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3000, 0x303F),  # CJK Symbols and Punctuation
    (0xFF00, 0xFFEF),  # Halfwidth and Fullwidth Forms
)


def is_ui_char(ch: str) -> bool:
    cp = ord(ch)
    if cp < 0x20:
        return False
    if ch in PUNCT:
        return True
    return any(lo <= cp <= hi for lo, hi in CJK_RANGES)


def collect_chars(dict_path: Path) -> tuple[set[str], int]:
    chars: set[str] = set()

    if dict_path.exists():
        data = json.loads(dict_path.read_text(encoding="utf-8-sig"))
        before = len(chars)
        for v in data.values():
            for ch in v:
                if ord(ch) >= 0x20:
                    chars.add(ch)
        print(f"  {dict_path.name}: {len(data)} entries, +{len(chars) - before} new chars")
    else:
        print(f"  ! missing dict, skipped: {dict_path}")

    before = len(chars)
    scanned = 0
    if MENU is not None and MENU.is_dir():
        for f in sorted(MENU.glob("*.cpp")):
            scanned += 1
            for ch in f.read_text(encoding="utf-8-sig", errors="replace"):
                if is_ui_char(ch):
                    chars.add(ch)
        print(f"  menu/*.cpp ({scanned} files): +{len(chars) - before} new chars")
    else:
        print("  ! menu directory unknown, source scan skipped")

    # ASCII printable always, so merged Latin text keeps working.
    chars.update(chr(cp) for cp in range(0x20, 0x7F))
    chars.update(PUNCT)
    return chars, scanned


# --------------------------------------------------------------------------- #
# stb_compress (the format Dear ImGui's stb_decompress reads)
# --------------------------------------------------------------------------- #
def stb_compress(inp: bytes) -> bytes:
    """Emit an stb-compressed stream.

    Header (16 bytes): magic 0x57BC0000, 4 zero bytes, original length BE,
    4 zero bytes. Body is a token stream; 0x05 0xFA then "Jro#" terminates it.
    """
    n = len(inp)
    out = bytearray()
    out += struct.pack(">I", 0x57BC0000)
    out += b"\x00\x00\x00\x00"
    out += struct.pack(">I", n)
    out += b"\x00\x00\x00\x00"

    WINDOW = 0x7FFFF  # max distance encodable by the 0x18-token
    MAX_MATCH = 256  # keeps every match inside the 1-byte length forms
    HASH_BITS = 16
    head = [-1] * (1 << HASH_BITS)
    prev = [-1] * n

    def h3(i: int) -> int:
        return ((inp[i] << 16) ^ (inp[i + 1] << 8) ^ inp[i + 2]) & ((1 << HASH_BITS) - 1)

    def emit_literal(start: int, length: int) -> None:
        nonlocal out
        while length > 0:
            chunk = min(length, 32)  # c in 0x20..0x3F -> 1..32 literal bytes
            out.append(0x20 + chunk - 1)
            out += inp[start : start + chunk]
            start += chunk
            length -= chunk

    def emit_match(dist: int, length: int) -> None:
        if dist <= 0x100 and length <= 0x80:
            out.append(0x80 + length - 1)
            out.append(dist - 1)
            return
        if dist <= 0x4000 and length <= 0x100:
            v = (dist - 1) + 0x4000
            out.append((v >> 8) & 0xFF)
            out.append(v & 0xFF)
            out.append(length - 1)
            return
        if dist <= 0x80000 and length <= 0x100:
            v = (dist - 1) + 0x180000
            out.append((v >> 16) & 0xFF)
            out.append((v >> 8) & 0xFF)
            out.append(v & 0xFF)
            out.append(length - 1)
            return
        if dist <= 0x80000:
            v = (dist - 1) + 0x100000
            out.append((v >> 16) & 0xFF)
            out.append((v >> 8) & 0xFF)
            out.append(v & 0xFF)
            out.append((length - 1) >> 8)
            out.append((length - 1) & 0xFF)
            return
        raise ValueError(f"match too far: dist={dist}")

    lit_start = 0
    i = 0
    while i + 2 < n:
        h = h3(i)
        cand = head[h]
        best_len = 0
        best_dist = 0
        tries = 0
        while cand >= 0 and tries < 64:
            dist = i - cand
            if dist > WINDOW:
                break
            # quick reject: byte best_len must still line up.
            # Both bounds matter: cand < i, so cand+best_len < n does NOT imply
            # i+best_len < n (the original in-tree script only checked the first
            # and could raise IndexError on short, highly repetitive tails).
            if (best_len and cand + best_len < n and i + best_len < n
                    and inp[cand + best_len] != inp[i + best_len]):
                cand = prev[cand]
                tries += 1
                continue
            if True:
                ln = 0
                while ln < MAX_MATCH and i + ln < n and inp[cand + ln] == inp[i + ln]:
                    ln += 1
                if ln > best_len:
                    best_len = ln
                    best_dist = dist
                    if ln >= 258:
                        break
            cand = prev[cand]
            tries += 1

        if best_len >= 3:
            if i > lit_start:
                emit_literal(lit_start, i - lit_start)
            emit_match(best_dist, best_len)
            end = i + best_len
            while i < end:
                if i + 2 < n:
                    h = h3(i)
                    prev[i] = head[h]
                    head[h] = i
                i += 1
            lit_start = i
        else:
            prev[i] = head[h]
            head[h] = i
            i += 1

    if lit_start < n:
        emit_literal(lit_start, n - lit_start)

    out += b"\x05\xFA"
    out += b"Jro#"
    return bytes(out)


def stb_decompress(data: bytes) -> bytes:
    def in4(x: int) -> int:
        return (data[x] << 24) + (data[x + 1] << 16) + (data[x + 2] << 8) + data[x + 3]

    if in4(0) != 0x57BC0000:
        raise SystemExit(f"bad magic: {in4(0):08x}")
    if in4(4) != 0:
        raise SystemExit("bad header word 4")
    olen = in4(8)
    out = bytearray(olen)
    dout = 0
    i = 16

    def copy_back(dist: int, length: int) -> None:
        """Overlapping-safe LZ copy: stb repeats byte-by-byte, so dist<length
        must replicate the growing run, not a snapshot of it."""
        nonlocal dout
        start = dout - dist
        if dist >= length:
            out[dout : dout + length] = out[start : start + length]
            dout += length
        else:
            for k in range(length):
                out[dout + k] = out[start + k]
            dout += length

    while True:
        c = data[i]
        if c >= 0x80:
            copy_back(data[i + 1] + 1, c - 0x80 + 1)
            i += 2
        elif c >= 0x40:
            length = data[i + 2] + 1
            copy_back(((c << 8) + data[i + 1]) - 0x4000 + 1, length)
            i += 3
        elif c >= 0x20:
            length = c - 0x20 + 1
            out[dout : dout + length] = data[i + 1 : i + 1 + length]
            dout += length
            i += 1 + length
        elif c >= 0x18:
            length = data[i + 3] + 1
            copy_back((((c << 16) + (data[i + 1] << 8) + data[i + 2]) - 0x180000) + 1, length)
            i += 4
        elif c >= 0x10:
            length = ((data[i + 3] << 8) + data[i + 4]) + 1
            copy_back((((c << 16) + (data[i + 1] << 8) + data[i + 2]) - 0x100000) + 1, length)
            i += 5
        elif c >= 0x08:
            length = ((c << 8) + data[i + 1]) - 0x0800 + 1
            out[dout : dout + length] = data[i + 2 : i + 2 + length]
            dout += length
            i += 2 + length
        elif c == 0x07:
            length = ((data[i + 1] << 8) + data[i + 2]) + 1
            out[dout : dout + length] = data[i + 3 : i + 3 + length]
            dout += length
            i += 3 + length
        elif c == 0x06:
            length = data[i + 4] + 1
            copy_back(((data[i + 1] << 16) + (data[i + 2] << 8) + data[i + 3]) + 1, length)
            i += 5
        elif c == 0x04:
            length = ((data[i + 4] << 8) + data[i + 5]) + 1
            copy_back(((data[i + 1] << 16) + (data[i + 2] << 8) + data[i + 3]) + 1, length)
            i += 6
        elif c == 0x05 and data[i + 1] == 0xFA:
            if dout != olen:
                raise SystemExit(f"length mismatch: {dout} != {olen}")
            return bytes(out)
        else:
            raise SystemExit(f"bad token {c:#04x} at {i}")


# --------------------------------------------------------------------------- #
# header emission (same shape as binary_to_compressed_c -u8)
# --------------------------------------------------------------------------- #
def write_header(blob: bytes, out_path: Path, symbol: str = "cjk", source_name: str = "msyh_cjk.ttf") -> None:
    """Emit the same shape as `binary_to_compressed_c -u8`.

    The reference tool starts a new line whenever the current line already holds
    180+ characters, which is why its output lines are up to ~187 columns wide.
    Matching that exactly keeps the file diff-friendly with previously exported
    headers and avoids surprises for anyone regenerating with the C tool.
    """
    out = [
        "// Embedded CJK font subset generated for the Chinese UI.",
        f'// Exported using tools_cn/build_font.py (stb_compress, -u8, "{source_name}") {symbol}',
        f"static const unsigned int {symbol}_compressed_size = {len(blob)};",
        f"static const unsigned char {symbol}_compressed_data[{len(blob)}] =",
        "{",
    ]
    body: list[str] = []
    column = 0
    for b in blob:
        if column == 0:
            body.append("    ")
        token = f"{b},"
        body.append(token)
        column += len(token)
        if column >= 180:
            body.append("\n")
            column = 0
    if column != 0:
        body.append("\n")
    out.append("".join(body))
    out.append("};\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out), encoding="utf-8", newline="\n")


def cmap_of(path: Path, index: int = 0) -> dict:
    from fontTools.ttLib import TTFont

    f = TTFont(str(path), fontNumber=index)
    try:
        return f.getBestCmap() or {}
    finally:
        f.close()


# --------------------------------------------------------------------------- #
# resolution helpers
# --------------------------------------------------------------------------- #
def resolve_source(explicit: str | None) -> Path | None:
    """Three level fallback: bundled TTF -> Windows msyh.ttc -> None.

    The bundled subset makes CI deterministic: `C:\\Windows\\Fonts\\msyh.ttc`
    only exists on a machine with the Chinese font pack installed, and nothing
    guarantees that on a `windows-latest` runner.
    """
    if explicit:
        return Path(explicit)
    if BUNDLED_SOURCE.exists():
        print(f"      source: bundled {BUNDLED_SOURCE}")
        return BUNDLED_SOURCE
    if DEFAULT_SOURCE_WINDOWS.exists():
        print(f"      source: system {DEFAULT_SOURCE_WINDOWS}")
        return DEFAULT_SOURCE_WINDOWS
    return None


def source_missing_message() -> str:
    return (
        "ERROR: no usable CJK source font found.\n"
        f"  tried: {BUNDLED_SOURCE}\n"
        f"  tried: {DEFAULT_SOURCE_WINDOWS}\n"
        "  Fix: commit the ~551 KB subset as tools_cn/msyh_cjk.ttf "
        "(generate it once on a Windows box with:\n"
        "        python tools_cn/build_font.py --source C:\\Windows\\Fonts\\msyh.ttc "
        "--ttf-out tools_cn/msyh_cjk.ttf)\n"
        "  or pass --source explicitly."
    )


# --------------------------------------------------------------------------- #
# modes
# --------------------------------------------------------------------------- #
def run_selftest() -> int:
    """stb round-trip on pathological sizes; exit 0 only if all pass."""
    import random

    sizes = [0, 1, 3, 400, 2560, 5000, 20000, 70000, 300000]
    rng = random.Random(0x0D15EA5E)
    failures = 0
    print("stb_compress / stb_decompress round-trip selftest")

    for n in sizes:
        # Mix of incompressible bytes, repeated runs and long overlaps so every
        # emit_match() branch (short/near/far/long) is exercised.
        buf = bytearray()
        while len(buf) < n:
            kind = rng.randrange(3)
            if kind == 0:
                buf += bytes(rng.randrange(256) for _ in range(rng.randrange(1, 40)))
            elif kind == 1:
                buf += bytes([rng.randrange(256)]) * rng.randrange(1, 300)
            else:
                take = min(len(buf), rng.randrange(1, 200)) or 0
                buf += bytes(buf[-take:]) if take else b"\x00"
        data = bytes(buf[:n])

        blob = stb_compress(data)
        back = stb_decompress(blob)
        ok = back == data
        overhead = len(blob) - 20  # 16 byte header + 4 byte terminator
        print(f"  n={n:>6}  compressed={len(blob):>7}  "
              f"header_len={struct.unpack('>I', blob[8:12])[0]:>6}  "
              f"{'OK' if ok else 'MISMATCH'}"
              + ("" if n else f"  (empty payload, {overhead} bytes overhead)"))
        if not ok:
            failures += 1
        if n and struct.unpack(">I", blob[8:12])[0] != n:
            print(f"  FAIL header length {struct.unpack('>I', blob[8:12])[0]} != {n}",
                  file=sys.stderr)
            failures += 1
        if blob[-4:] != b"Jro#":
            print("  FAIL missing Jro# terminator", file=sys.stderr)
            failures += 1

    if failures:
        print(f"selftest FAILED ({failures} case(s))", file=sys.stderr)
        return 1
    print(f"selftest OK ({len(sizes)} sizes)")
    return 0


def coverage_report(src: Path, index: int, chars: set[str]) -> int:
    """Return 0 when every requested char has a glyph, 1 otherwise."""
    cmap = cmap_of(src, index)
    missing = sorted(c for c in chars if ord(c) not in cmap)
    print(f"      source cmap entries: {len(cmap)}")
    print(f"      requested chars: {len(chars)} "
          f"(non-ASCII: {sum(1 for c in chars if ord(c) > 0x7F)})")
    if missing:
        print(f"      MISSING {len(missing)} char(s):", file=sys.stderr)
        for ch in missing:
            # Print the code point, the glyph itself and its escape form. The
            # escape matters for combining marks and other invisible characters
            # that would otherwise look like a blank in the log.
            print(f"        U+{ord(ch):04X}  {ch}  {ascii(ch)}", file=sys.stderr)
        print(f"      all missing: {''.join(missing)}", file=sys.stderr)
        return 1
    print("      every requested char has a glyph")
    return 0


def run_check(src: Path, index: int, dict_path: Path) -> int:
    print("[check] coverage only")
    chars, _ = collect_chars(dict_path)
    return coverage_report(src, index, chars)


def run_build(src: Path, index: int, dict_path: Path, out_dir: Path,
              ttf_out: Path | None) -> int:
    print("[1/5] collecting characters")
    chars, _ = collect_chars(dict_path)
    print(f"      total chars: {len(chars)}  "
          f"(non-ASCII: {sum(1 for c in chars if ord(c) > 0x7F)})")

    from fontTools import subset as ftsubset
    from fontTools.ttLib import TTFont

    tmpdir = Path(tempfile.mkdtemp(prefix="cjkfont-"))
    subset_path = ttf_out if ttf_out else tmpdir / "msyh_cjk.ttf"

    print(f"[2/5] subsetting {src.name} (index {index}) -> {subset_path.name}")
    options = ftsubset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.notdef_outline = True
    options.recalc_bounds = True
    options.drop_tables = []

    # fontTools' subset.load_font() has no fontNumber argument, so a TrueType
    # Collection has to be reduced to a single face first.
    flat = src
    if src.suffix.lower() in (".ttc", ".otc"):
        flat = tmpdir / f"{src.stem}-face{index}.ttf"
        face = TTFont(str(src), fontNumber=index, lazy=False)
        face.save(str(flat))
        face.close()
        print(f"      extracted face {index} -> {flat.name}")

    font = ftsubset.load_font(str(flat), options)
    subsetter = ftsubset.Subsetter(options=options)
    subsetter.populate(unicodes={ord(c) for c in chars})
    subsetter.subset(font)
    subset_path.parent.mkdir(parents=True, exist_ok=True)
    ftsubset.save_font(font, str(subset_path), options)
    font.close()
    ttf = subset_path.read_bytes()
    print(f"      {subset_path}: {len(ttf)} bytes")

    print("[3/5] verifying coverage")
    rc = coverage_report(subset_path, 0, chars)
    if rc != 0:
        print("ERROR: subset is missing glyphs, refusing to emit a broken header",
              file=sys.stderr)
        if not ttf_out:
            for p in tmpdir.glob("*"):
                p.unlink(missing_ok=True)
            tmpdir.rmdir()
        return 1

    print("[4/5] stb_compress")
    blob = stb_compress(ttf)
    print(f"      {len(ttf)} -> {len(blob)} bytes (ratio {len(blob)/len(ttf):.3f})")

    print("[5/5] round-trip + emit header")
    back = stb_decompress(blob)
    if back != ttf:
        print("      ERROR: round-trip mismatch", file=sys.stderr)
        return 1
    header = out_dir / "CJK_Compressed.h"
    write_header(blob, header, symbol="cjk", source_name=subset_path.name)
    print(f"      {header}: {header.stat().st_size} bytes")
    print(f"      cjk_compressed_size = {len(blob)}")
    print(f"      cjk_compressed_data[{len(blob)}]")

    # Re-open the decompressed bytes with fontTools to make sure the emitted
    # blob is a font stb_truetype can actually read.
    import io

    from fontTools.ttLib import TTFont as FT

    FT(io.BytesIO(back)).getBestCmap()
    print("      decompressed blob parses as a valid font")

    if not ttf_out:
        for p in tmpdir.glob("*"):
            p.unlink(missing_ok=True)
        tmpdir.rmdir()
    return 0


def main() -> int:
    global MENU

    ap = argparse.ArgumentParser(
        description="Build OptiScaler/menu/font/CJK_Compressed.h from a CJK font.")
    ap.add_argument("--out", type=Path,
                    help="output directory for CJK_Compressed.h "
                         "(default: <repo>/OptiScaler/menu/font)")
    ap.add_argument("--repo", type=Path,
                    help="root of the upstream OptiScaler checkout, used to scan "
                         "OptiScaler/menu/*.cpp for characters already in the source")
    ap.add_argument("--source",
                    help="source font (.ttf/.ttc); default: try tools_cn/msyh_cjk.ttf "
                         r"then C:\Windows\Fonts\msyh.ttc")
    ap.add_argument("--index", type=int, default=0,
                    help="face index for a .ttc/.otc collection (default 0)")
    ap.add_argument("--dict", type=Path, default=DEFAULT_DICT,
                    help="dictionary whose translations must be covered "
                         "(default: tools_cn/dict_v10.json)")
    ap.add_argument("--ttf-out", type=Path,
                    help="keep the subsetted font at this path instead of a temp file")
    ap.add_argument("--selftest", action="store_true",
                    help="only run the stb compress/decompress round-trip selftest")
    ap.add_argument("--check", action="store_true",
                    help="only verify that the source font covers every needed char")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()

    if args.repo:
        MENU = args.repo.resolve() / "OptiScaler" / "menu"

    # --check never writes a header, so it does not need an output directory.
    out_dir = args.out
    scratch_out = None
    if not args.check:
        if out_dir is None:
            if args.repo:
                out_dir = args.repo.resolve() / "OptiScaler" / "menu" / "font"
            elif args.ttf_out:
                # Documented use case: refresh tools_cn/msyh_cjk.ttf only. The
                # header still has to be produced, so build it somewhere
                # disposable instead of demanding an otherwise pointless --out.
                scratch_out = Path(tempfile.mkdtemp(prefix="cjkfont-out-"))
                out_dir = scratch_out
                print(f"note: no --out given, header goes to a temp dir "
                      f"({out_dir}) because --ttf-out was requested")
            else:
                print("ERROR: --out (or --repo) is required to build the header",
                      file=sys.stderr)
                return 2
        out_dir = out_dir.resolve()

    if args.check and not (MENU is not None and MENU.is_dir()):
        # --check still wants to include chars already present in the sources,
        # but it can run against the dictionary alone.
        print("WARNING: no --repo given, only dictionary characters are checked")

    src = resolve_source(args.source)
    if src is None:
        print(source_missing_message(), file=sys.stderr)
        return 1
    if not src.exists():
        print(f"ERROR: source font not found: {src}", file=sys.stderr)
        return 1

    if args.check:
        return run_check(src, args.index, args.dict)

    try:
        rc = run_build(src, args.index, args.dict, out_dir, args.ttf_out)
    finally:
        if scratch_out is not None:
            for p in scratch_out.glob("*"):
                p.unlink(missing_ok=True)
            scratch_out.rmdir()
    if rc == 0 and args.ttf_out:
        print(f"      kept subset at {args.ttf_out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
