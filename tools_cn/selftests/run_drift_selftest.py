#!/usr/bin/env python3
"""Drift regression test for tools_cn/localize.py.

Why this exists
---------------
Anchor drift used to be a *silent* success: if upstream renamed the include or
moved the font-loading ``if`` block, ``apply_font()`` skipped the injection and
still printed "CJK font integration applied", so CI stayed green while the
produced DLL had no Chinese glyphs at all. This test pins the opposite
behaviour: every drift case must exit non-zero.

Cases
-----
A  pristine fixture                                     -> exit 0, both halves injected
A' same checkout again                                  -> exit 0, 0 keys translated (idempotent)
B  block anchor drifted                                 -> exit != 0, file not rewritten
C  include anchor drifted                               -> exit != 0, file not rewritten
D  both anchors drifted                                 -> exit != 0, file not rewritten
E  half-injected (include in, block out)                -> exit != 0, file not rewritten
F  untranslated but otherwise valid checkout, --verify  -> exit != 0
G  block anchor re-indented 4 -> 8 spaces                -> exit 0, both halves injected
H  block anchor wrapped in /* ... */ (dead code)         -> exit != 0
I  include anchor wrapped in #if 0                       -> exit != 0
J  anchor twice, first copy commented out                -> exit != 0

G is an *accept* case on purpose. ``FONT_BLOCK_ANCHOR`` carries a 4-space
prefix, and a line indented by 8 spaces still contains that substring, so
``text.count()`` stays 1 and ``str.replace()`` still inserts at the right
place: re-indenting the surrounding block is a benign upstream change, not
drift. Do not "fix" this by requiring the anchor to start at column 4 - that
would turn harmless reformatting into a build failure. Only a *missing* or
*duplicated* anchor is fatal, which is what B/C/D/E pin down.

H and I are the "anchor is present but the code is dead" pair, and H is the one
that used to be a product-level false green: with the block anchor inside
``/* ... */`` the merge block was spliced into the comment, ``cjk_compressed_data``
was declared but never referenced, cl.exe compiled it without a warning, and the
resulting DLL advertised Chinese text with no Chinese glyphs - while
``verify_binary.py`` still passed, because the UTF-8 literals really were in
``.rdata``. Both cases are now counted on a comment-free view of the source
(``localize.strip_noncode``), so they must exit non-zero. I alone would have
failed to link (an include inside ``#if 0`` leaves the array undeclared), but
covering it costs one line and makes the rule uniform.

J is the case that pins the *post*-injection guard specifically. In H the anchor
is the only copy, so the comment-free pre-check already refuses to inject and
the "did the block land in a comment?" check never fires. In J the anchor exists
twice - first commented out, then live - so the pre-check sees exactly one
reachable anchor and proceeds, while ``str.replace(..., 1)`` rewrites the
commented copy. Only re-counting the marker in the code view *after* the
replace catches that, which is why J is here: without it, deleting that
post-check would leave this suite green.

The fixture is tools_cn/selftests/menu_common_fixture.cpp, not the real
upstream file: this job must stay fast and must not need a 1.5 GB clone. The
trade-off is documented in that fixture's header comment - if upstream changes
the anchors, the fixture and localize.py have to be updated together, and this
test is what makes that failure loud instead of silent.

Usage:
    python tools_cn/selftests/run_drift_selftest.py
    python tools_cn/selftests/run_drift_selftest.py --keep   # leave temp dirs
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
LOCALIZE = TOOLS / "localize.py"
FIXTURE = HERE / "menu_common_fixture.cpp"

INCLUDE_ANCHOR = '#include "font/Hack_Compressed.h"'
INCLUDE_LINE = '#include "font/CJK_Compressed.h"'
BLOCK_ANCHOR = "    if (!Config::Instance()->OverlayMenu.value_or_default())"
BLOCK_MARKER = "[CN] Merge the embedded CJK subset font"

# A synthetic but self-consistent stand-in for the header build_font.py emits.
# localize.py's post-condition check only reads the two declarations, so a
# real 1.5 MB header would slow this test down for no benefit.
FAKE_HEADER = """#pragma once

static const unsigned int cjk_compressed_size = 8;
static const unsigned char cjk_compressed_data[8] = {0, 0, 0, 0, 0, 0, 0, 0};
"""


def build_checkout(root: Path, source: str) -> Path:
    """Materialize a fake checkout at *root* with *source* as menu_common.cpp."""
    menu = root / "OptiScaler" / "menu"
    (menu / "font").mkdir(parents=True, exist_ok=True)
    (menu / "menu_common.cpp").write_text(source, encoding="utf-8", newline="\n")
    (menu / "font" / "CJK_Compressed.h").write_text(FAKE_HEADER, encoding="utf-8",
                                                    newline="\n")
    return root


def run_localize(repo: Path, *extra: str) -> tuple:
    argv = [sys.executable, str(LOCALIZE), "--repo", str(repo), "--tools", str(TOOLS)]
    argv.extend(extra)
    proc = subprocess.run(argv, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def has_both_halves(repo: Path) -> bool:
    text = (repo / "OptiScaler" / "menu" / "menu_common.cpp").read_text(encoding="utf-8")
    return INCLUDE_LINE in text and BLOCK_MARKER in text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", action="store_true",
                    help="keep the temporary checkouts for inspection")
    args = ap.parse_args()

    if not FIXTURE.is_file():
        print(f"ERROR: fixture missing: {FIXTURE}", file=sys.stderr)
        return 1

    pristine = FIXTURE.read_text(encoding="utf-8")
    if pristine.count(INCLUDE_ANCHOR) != 1:
        print(f"ERROR: the fixture must contain {INCLUDE_ANCHOR!r} exactly once, "
              f"found {pristine.count(INCLUDE_ANCHOR)}", file=sys.stderr)
        return 1
    if pristine.count(BLOCK_ANCHOR) != 1:
        print(f"ERROR: the fixture must contain {BLOCK_ANCHOR!r} exactly once, "
              f"found {pristine.count(BLOCK_ANCHOR)}", file=sys.stderr)
        return 1
    if INCLUDE_LINE in pristine or BLOCK_MARKER in pristine:
        print("ERROR: the fixture is already localized; it must stay pristine",
              file=sys.stderr)
        return 1

    drift_cases = {
        "B_block_drift": pristine.replace(
            BLOCK_ANCHOR,
            "    if (!Config::Instance()->OverlayMenu.value_or_default() || true)"),
        "C_include_drift": pristine.replace(
            INCLUDE_ANCHOR, '#include "font/Hack_Compressed_renamed.h"'),
        "D_both_drift": pristine.replace(
            BLOCK_ANCHOR, "    if (somethingElse())").replace(
            INCLUDE_ANCHOR, '#include "font/Hack_Compressed_renamed.h"'),
        "E_half_injected": pristine.replace(
            INCLUDE_ANCHOR, INCLUDE_ANCHOR + "\n" + INCLUDE_LINE, 1),
    }

    for name, text in drift_cases.items():
        if name.startswith(("C_", "D_")) and INCLUDE_ANCHOR in text:
            print(f"ERROR: fixture for {name} still contains the include anchor",
                  file=sys.stderr)
            return 1
        if name in ("B_block_drift", "D_both_drift") and BLOCK_ANCHOR in text:
            print(f"ERROR: fixture for {name} still contains the block anchor",
                  file=sys.stderr)
            return 1

    tmp_root = Path(tempfile.mkdtemp(prefix="drift-selftest-"))
    failures = []
    try:
        # ---- A: the pristine fixture must succeed and inject both halves ----
        a_dir = build_checkout(tmp_root / "A_pristine", pristine)
        code, out = run_localize(a_dir)
        injected = has_both_halves(a_dir)
        print(f"A_pristine          exit={code}  both halves injected={injected}")
        if code != 0:
            failures.append(f"A_pristine exited {code} but should have succeeded")
            print(out, file=sys.stderr)
        elif not injected:
            failures.append("A_pristine exited 0 but did not inject both halves")
            print(out, file=sys.stderr)

        # ---- A': idempotency ----
        code2, out2 = run_localize(a_dir)
        zero = "Total keys translated: 0" in out2
        print(f"A'_second_run       exit={code2}  reported 0 translations={zero}")
        if code2 != 0:
            failures.append(f"the second run exited {code2} but must stay idempotent")
            print(out2, file=sys.stderr)
        elif not zero:
            failures.append("the second run was not idempotent (keys were retranslated)")
            print(out2, file=sys.stderr)
        if not has_both_halves(a_dir):
            failures.append("the second run removed one of the injected halves")

        # ---- B/C/D/E: every drift case must fail ----
        for name, text in drift_cases.items():
            repo = build_checkout(tmp_root / name, text)
            # E starts out half-injected on purpose, so its input already has
            # the include; the "left a half-injected file behind" assertion only
            # makes sense for the cases that start pristine.
            started_pristine = name != "E_half_injected"
            code, out = run_localize(repo)
            ok = code != 0
            print(f"{name:<19} exit={code}  rejected={ok}")
            if not ok:
                failures.append(f"{name} exited 0 but anchor drift must be fatal")
                print(out, file=sys.stderr)
            written = (repo / "OptiScaler" / "menu" / "menu_common.cpp").read_text(
                encoding="utf-8")
            if has_both_halves(repo):
                failures.append(f"{name} injected both halves despite the drift")
            elif started_pristine and code != 0 and (INCLUDE_LINE in written or
                                                     BLOCK_MARKER in written):
                failures.append(f"{name} left a half-injected file behind after failing")
            # The injection must not have happened *anywhere*: the drifted
            # anchor has to survive verbatim. A byte-identity check against the
            # input would be wrong here - apply_dict() runs before apply_font()
            # and legitimately rewrites the translated string literals, so only
            # the injection point itself is meaningful.
            drifted = drift_cases[name]
            for anchor in (INCLUDE_LINE, BLOCK_MARKER):
                before = drifted.count(anchor)
                after = written.count(anchor)
                if after != before:
                    failures.append(f"{name} changed the number of {anchor!r} "
                                    f"({before} -> {after}) despite failing")

        # ---- F: --verify on an untranslated checkout must fail ----
        f_dir = build_checkout(tmp_root / "F_untranslated", pristine)
        f_cpp = f_dir / "OptiScaler" / "menu" / "menu_common.cpp"
        f_before = f_cpp.read_bytes()
        code, out = run_localize(f_dir, "--verify")
        print(f"F_verify_untranslated exit={code}  rejected={code != 0}")
        if code == 0:
            failures.append("--verify accepted a checkout without the localization")
            print(out, file=sys.stderr)
        # --verify is a read-only assertion mode: it must never rewrite the file
        # it is complaining about, otherwise a failed check could mask itself.
        if f_cpp.read_bytes() != f_before:
            failures.append("--verify modified menu_common.cpp; it must be read-only")

        # ---- G: a re-indented block anchor must still be accepted ----
        # The anchor carries a 4-space prefix and an 8-space line still
        # contains it, so the injection point is still unique: this is a benign
        # upstream reformat, not drift. Pinned here so nobody "hardens" the
        # anchor into a column-exact match later and breaks harmless reindents.
        g_source = pristine.replace(BLOCK_ANCHOR, "    " + BLOCK_ANCHOR, 1)
        if g_source.count(BLOCK_ANCHOR) != 1:
            print("ERROR: case G unexpectedly lost the block anchor", file=sys.stderr)
            return 1
        g_dir = build_checkout(tmp_root / "G_reindented", g_source)
        code, out = run_localize(g_dir)
        injected = has_both_halves(g_dir)
        print(f"G_reindented_anchor exit={code}  both halves injected={injected}")
        if code != 0:
            failures.append(f"G_reindented exited {code}; a benign re-indent must "
                            f"not be treated as anchor drift")
            print(out, file=sys.stderr)
        elif not injected:
            failures.append("G_reindented exited 0 but did not inject both halves")
            print(out, file=sys.stderr)

        # ---- H/I: anchors that exist but sit in dead code must be fatal ----
        # H is the product-level false green this suite was extended for. The
        # block anchor is still there character for character, so a naive
        # str.count() finds it once and the merge block is spliced *into the
        # comment*: dead code, undeclared-but-unused array, cl.exe is happy, and
        # the DLL ships without a single Chinese glyph. Counting on the
        # comment-free view turns it into a hard error.
        dead_cases = {
            "H_anchor_commented_out": pristine.replace(
                BLOCK_ANCHOR, "/*\n" + BLOCK_ANCHOR + "\n*/", 1),
            # I is the checker-level variant: an include inside #if 0 leaves
            # cjk_compressed_data undeclared, so the build would fail to link.
            # Not a silent failure, but the same rule catches it for free.
            "I_include_if0": pristine.replace(
                INCLUDE_ANCHOR, "#if 0\n" + INCLUDE_ANCHOR + "\n#endif", 1),
            # J exists so the *post-injection* guard has a case that only it can
            # catch. The anchor appears twice: the first copy is commented out,
            # the second is live. strip_noncode() therefore still sees exactly one
            # reachable anchor and the pre-check is happy, but text.replace(.., 1)
            # hits the commented copy first, so the merge block lands in the
            # comment. Only "re-count the marker in the code view after the
            # replace" notices that. Without J, deleting that post-check would
            # leave the suite green and the guard untested.
            "J_dup_anchor_first_dead": pristine.replace(
                BLOCK_ANCHOR, "/*\n" + BLOCK_ANCHOR + "\n*/\n" + BLOCK_ANCHOR, 1),
        }
        for name, text in dead_cases.items():
            repo = build_checkout(tmp_root / name, text)
            before_cpp = repo / "OptiScaler" / "menu" / "menu_common.cpp"
            before = before_cpp.read_text(encoding="utf-8")
            code, out = run_localize(repo)
            written = before_cpp.read_text(encoding="utf-8")
            print(f"{name:<19} exit={code}  rejected={code != 0}")
            if code == 0:
                failures.append(f"{name} exited 0 but an anchor inside dead code "
                                f"must be fatal")
                print(out, file=sys.stderr)
            # Nothing may have been injected anywhere in the file either.
            for anchor in (INCLUDE_LINE, BLOCK_MARKER):
                if written.count(anchor) != before.count(anchor):
                    failures.append(f"{name} injected {anchor!r} despite the anchor "
                                    f"being dead code")
    finally:
        if args.keep:
            print(f"checkouts kept in {tmp_root}")
        else:
            shutil.rmtree(tmp_root, ignore_errors=True)

    if failures:
        print("", file=sys.stderr)
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        print(f"drift selftest FAILED ({len(failures)} problem(s))", file=sys.stderr)
        return 1

    print("drift selftest OK (pristine accepted, all drift cases rejected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
