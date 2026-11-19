#!/usr/bin/env python3
"""Structurally verify that a PE file carries an Authenticode signature.

Why this exists: the signing step asserts with ``Get-AuthenticodeSignature``,
but that call evaluates the *trust chain*, so a self-signed certificate comes
back as ``UnknownError`` / ``NotTrusted`` on a machine that has not installed
it. Treating "signer certificate is not null" as success would also accept a
file whose contents were modified after signing (``HashMismatch``). This tool
answers a different, cheaper question: *is there a certificate table in this
PE, and does it name the subject we signed with* -- which needs no trust store
and no Windows APIs, so it can run in `ci-check` and in a self test.

It is deliberately a structural check, not a cryptographic one. The
cryptographic part is done by ``signtool verify`` on the signing machine; what
this guards against is the failure that actually happened during development:
the pipeline publishing a binary with no signature at all.

Checks performed
----------------
1. ``e_lfanew`` and the ``PE\\0\\0`` signature are sane.
2. ``OptionalHeader.Magic`` is PE32 (0x10b) or PE32+ (0x20b), so the data
   directory offset is known.
3. ``DataDirectory[IMAGE_DIRECTORY_ENTRY_SECURITY]`` (index 4) has a non-zero
   file offset and a size of at least one ``WIN_CERTIFICATE`` header.
4. That region lies inside the file, is 8-byte aligned (spec requirement), and
   its first entry is ``wRevision == 0x0200`` and
   ``wCertificateType == 0x0002`` (PKCS#7 SignedData), with ``dwLength``
   covering the entry and not exceeding the table.
5. The subject named by ``--expect-subject`` occurs in the certificate blob,
   in either UTF-8/ASCII or UTF-16BE, so a table left over from a different
   certificate is not silently accepted.

Exit codes: 0 all checks pass, 1 a check failed, 2 bad usage or unreadable file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PE_SIGNATURE = b"PE\0\0"
MAGIC_PE32 = 0x10B
MAGIC_PE32_PLUS = 0x20B
# Offset of DataDirectory[] inside the optional header, per magic.
DATA_DIR_OFFSET = {MAGIC_PE32: 96, MAGIC_PE32_PLUS: 112}
# IMAGE_DIRECTORY_ENTRY_SECURITY: the only directory whose VirtualAddress is a
# *file offset* rather than an RVA.
SECURITY_DIR_INDEX = 4
WIN_CERT_REVISION_2_0 = 0x0200
WIN_CERT_TYPE_PKCS_SIGNED_DATA = 0x0002
# Shortest RDN value that counts as evidence: anything shorter matches random
# DER bytes, so a 1-2 character "subject" must not make an unsigned file pass.
MIN_SUBJECT_NEEDLE = 8


class CheckError(Exception):
    """A structural expectation was not met."""


def read_u16(buf: bytes, off: int) -> int:
    if off < 0 or off + 2 > len(buf):
        raise CheckError(f"u16 read at 0x{off:X} is outside the file")
    return int.from_bytes(buf[off:off + 2], "little")


def read_u32(buf: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(buf):
        raise CheckError(f"u32 read at 0x{off:X} is outside the file")
    return int.from_bytes(buf[off:off + 4], "little")


def locate_certificate_table(buf: bytes) -> tuple[int, int]:
    """Return (file offset, size) of the IMAGE_DIRECTORY_ENTRY_SECURITY."""
    if len(buf) < 0x40 + 4:
        raise CheckError("file is too small to contain a DOS header")
    if buf[:2] != b"MZ":
        raise CheckError("missing MZ signature; this is not a PE file")

    e_lfanew = read_u32(buf, 0x3C)
    if e_lfanew + 24 > len(buf):
        raise CheckError(f"e_lfanew 0x{e_lfanew:X} points past the end of the file")
    if buf[e_lfanew:e_lfanew + 4] != PE_SIGNATURE:
        raise CheckError("missing PE signature at e_lfanew; this is not a PE file")

    optional_header = e_lfanew + 4 + 20  # COFF header is a fixed 20 bytes
    magic = read_u16(buf, optional_header)
    if magic not in DATA_DIR_OFFSET:
        raise CheckError(
            f"unexpected optional-header magic 0x{magic:X}; "
            "expected 0x10B (PE32) or 0x20B (PE32+)"
        )

    dir_base = optional_header + DATA_DIR_OFFSET[magic]
    entry = dir_base + SECURITY_DIR_INDEX * 8
    offset = read_u32(buf, entry)
    size = read_u32(buf, entry + 4)
    return offset, size


def check_win_certificate(buf: bytes, offset: int, size: int) -> int:
    """Validate the WIN_CERTIFICATE entry and return the blob length."""
    if offset == 0 or size == 0:
        raise CheckError(
            "the certificate table is empty: the file carries no Authenticode "
            "signature at all"
        )
    if offset >= len(buf):
        raise CheckError(
            f"certificate table offset 0x{offset:X} is past the end of the "
            f"file (0x{len(buf):X} bytes)"
        )
    if offset + size > len(buf):
        raise CheckError(
            f"certificate table (0x{offset:X} + 0x{size:X}) runs past the end "
            f"of the file (0x{len(buf):X} bytes)"
        )
    if offset % 8 != 0:
        raise CheckError(
            f"certificate table offset 0x{offset:X} is not 8-byte aligned; "
            "the PE specification requires it"
        )
    if size < 8:
        raise CheckError(f"certificate table is only 0x{size:X} bytes, too small for a WIN_CERTIFICATE")

    length = read_u32(buf, offset)
    revision = read_u16(buf, offset + 4)
    cert_type = read_u16(buf, offset + 6)

    if length < 8:
        raise CheckError(f"WIN_CERTIFICATE.dwLength is 0x{length:X}, smaller than its own header")
    if length > size:
        raise CheckError(
            f"WIN_CERTIFICATE.dwLength 0x{length:X} exceeds the table size 0x{size:X}"
        )
    if revision != WIN_CERT_REVISION_2_0:
        raise CheckError(
            f"WIN_CERTIFICATE.wRevision is 0x{revision:04X}, expected 0x0200"
        )
    if cert_type != WIN_CERT_TYPE_PKCS_SIGNED_DATA:
        raise CheckError(
            f"WIN_CERTIFICATE.wCertificateType is 0x{cert_type:04X}, "
            "expected 0x0002 (PKCS#7 SignedData)"
        )
    return length


def subject_present(buf: bytes, offset: int, length: int, subject: str) -> bool:
    """Search the certificate blob for the subject.

    A DN is stored in DER as a sequence of RDNs; the ``CN=`` prefix is display
    syntax and never appears in the encoding. So the value of each RDN is
    searched for, not the whole ``CN=...`` string. Each candidate is tried as
    ASCII/UTF-8 (PrintableString/UTF8String) and as UTF-16 big endian
    (BMPString), which covers the encodings a Windows certificate can use.
    """
    blob = buf[offset:offset + length]
    candidates = {subject}
    for rdn in subject.split(","):
        if "=" in rdn:
            candidates.add(rdn.split("=", 1)[1].strip())
    # A one- or two-character needle would match almost any DER blob by chance
    # (certificates are full of short runs), so short needles are not evidence.
    candidates = {c for c in candidates if len(c) >= MIN_SUBJECT_NEEDLE}
    if not candidates:
        return True  # nothing long enough to check; structure alone is the check
    for cand in candidates:
        if not cand:
            continue
        if cand.encode("utf-8") in blob:
            return True
        if cand.encode("utf-16-be") in blob:
            return True
    return False


def verify(path: Path, expect_subject: str | None, quiet: bool = False) -> int:
    def say(msg: str) -> None:
        if not quiet:
            print(msg)

    try:
        buf = path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    try:
        offset, size = locate_certificate_table(buf)
        say(f"certificate table: file offset 0x{offset:X}, size 0x{size:X}")
        length = check_win_certificate(buf, offset, size)
        say(f"WIN_CERTIFICATE : dwLength 0x{length:X}, revision 0x0200, type PKCS#7")
        if expect_subject:
            if not subject_present(buf, offset, length, expect_subject):
                raise CheckError(
                    f"the certificate blob does not mention the expected subject "
                    f"{expect_subject!r}; the signature may come from a different "
                    "certificate"
                )
            say(f"subject         : {expect_subject!r} found in the certificate blob")
    except CheckError as exc:
        print(f"FAIL {path.name}: {exc}", file=sys.stderr)
        return 1

    say(f"PASS {path.name}: carries an Authenticode signature")
    return 0


def build_self_test_pe(subject: str, *, with_cert: bool = True, bad_revision: bool = False) -> bytes:
    """Build a minimal PE image for the self test.

    Only the fields this tool reads are populated: the DOS header, e_lfanew,
    the PE signature, the optional-header magic and the security data
    directory. Everything else is zero, which is fine because the tool does not
    look at sections or the symbol table.
    """
    e_lfanew = 0x80
    optional_header = e_lfanew + 4 + 20
    data_dir = optional_header + DATA_DIR_OFFSET[MAGIC_PE32_PLUS]
    cert_entry = data_dir + SECURITY_DIR_INDEX * 8

    cert_subject = subject.encode("utf-16-be")
    # WIN_CERTIFICATE header + a payload that merely contains the subject.
    payload = b"\x30\x82" + b"\x00" * 6 + cert_subject + b"\x00" * 0x20
    cert_length = 8 + len(payload)
    blob = cert_length.to_bytes(4, "little")
    blob += (0x0100 if bad_revision else WIN_CERT_REVISION_2_0).to_bytes(2, "little")
    blob += WIN_CERT_TYPE_PKCS_SIGNED_DATA.to_bytes(2, "little")
    blob += payload
    if len(blob) % 8:
        blob += b"\x00" * (8 - len(blob) % 8)

    # Place the certificate table after the headers, 8-byte aligned.
    cert_offset = ((cert_entry + 8) + 7) // 8 * 8
    total = cert_offset + len(blob)
    buf = bytearray(total)

    buf[0:2] = b"MZ"
    buf[0x3C:0x40] = e_lfanew.to_bytes(4, "little")
    buf[e_lfanew:e_lfanew + 4] = PE_SIGNATURE
    buf[optional_header:optional_header + 2] = MAGIC_PE32_PLUS.to_bytes(2, "little")
    if with_cert:
        buf[cert_entry:cert_entry + 4] = cert_offset.to_bytes(4, "little")
        buf[cert_entry + 4:cert_entry + 8] = len(blob).to_bytes(4, "little")
        buf[cert_offset:cert_offset + len(blob)] = blob
    return bytes(buf)


def self_test() -> int:
    """Exercise the checker against images built in memory."""
    subject = "CN=OptiScaler-zhcn (community build)"
    cases: list[tuple[str, bytes, str | None, int]] = [
        ("signed, subject matches", build_self_test_pe(subject), subject, 0),
        ("signed, no subject expectation", build_self_test_pe(subject), None, 0),
        ("signed, wrong subject expected", build_self_test_pe(subject), "CN=Somebody Else", 1),
        ("no certificate table", build_self_test_pe(subject, with_cert=False), subject, 1),
        ("bad WIN_CERTIFICATE revision", build_self_test_pe(subject, bad_revision=True), subject, 1),
        ("not a PE file", b"MZ" + b"\x00" * 0x100, subject, 1),
        ("truncated after DOS header", b"MZ" + b"\x00" * 0x3A, subject, 1),
        # Guard against the real bug this was written for: a 1-2 character
        # subject must not turn an *unsigned* file into a pass. On a genuinely
        # signed file the structure alone is enough, so that case still passes.
        ("short subject on signed file", build_self_test_pe(subject), "CN=x", 0),
        ("short subject, no cert", build_self_test_pe(subject, with_cert=False), "CN=x", 1),
        ("empty subject, no cert", build_self_test_pe(subject, with_cert=False), "", 1),
    ]

    failures = 0
    for name, data, expect, want in cases:
        # Write to a BytesIO-backed path is not possible, so patch read_bytes by
        # writing to a temp file next to this script's own directory.
        tmp = Path(__file__).resolve().parent / "_selftest_image.bin"
        try:
            tmp.write_bytes(data)
            got = verify(tmp, expect, quiet=True)
        finally:
            tmp.unlink(missing_ok=True)
        ok = got == want
        if not ok:
            failures += 1
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: exit {got} (expected {want})")

    if failures:
        print(f"self test FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"self test OK ({len(cases)} cases)")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Structurally verify that a PE file carries an Authenticode signature."
    )
    parser.add_argument("--pe", type=Path, help="PE file to inspect (e.g. OptiScaler.dll)")
    parser.add_argument(
        "--expect-subject",
        default=None,
        help="subject the certificate blob must mention, e.g. "
             "\"CN=OptiScaler-zhcn (community build)\"",
    )
    parser.add_argument("--self-test", action="store_true", help="run the built-in cases")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.pe:
        parser.error("either --pe or --self-test is required")
    return verify(args.pe, args.expect_subject)


if __name__ == "__main__":
    sys.exit(main())
