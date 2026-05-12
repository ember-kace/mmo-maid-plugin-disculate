"""Build the production bundle.

Deterministic zip (all mtimes set to epoch 0) with an explicit allowlist.
Anything not on the allowlist is rejected — guards against accidentally
shipping tests/, tools/, .md, or backup files.

Run from project root:
    py tools/build_bundle.py
"""

from __future__ import annotations

import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "build")
OUT_PATH = os.path.join(OUT_DIR, "disculate.zip")

INCLUDED_FILES = [
    "manifest.json",
    "plugin.py",
    "requirements.txt",
    "lib/__init__.py",
    "lib/config.py",
    "lib/diagnostics.py",
    "lib/embed.py",
    "lib/format.py",
    "lib/functions.py",
    "lib/logctx.py",
    "lib/parser.py",
    "lib/reasons.py",
    "lib/walker.py",
]


def build() -> str:
    os.makedirs(OUT_DIR, exist_ok=True)

    missing = [p for p in INCLUDED_FILES if not os.path.isfile(os.path.join(ROOT, p))]
    if missing:
        raise SystemExit(f"build_bundle: missing files: {missing}")

    if os.path.exists(OUT_PATH):
        os.remove(OUT_PATH)

    with zipfile.ZipFile(OUT_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDED_FILES:
            src = os.path.join(ROOT, rel)
            with open(src, "rb") as f:
                data = f.read()
            info = zipfile.ZipInfo(filename=rel.replace(os.sep, "/"))
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)

    with zipfile.ZipFile(OUT_PATH) as zf:
        names = sorted(zf.namelist())
        total_compressed = os.path.getsize(OUT_PATH)
        total_uncompressed = sum(i.file_size for i in zf.infolist())

    print(f"\nbundle: {OUT_PATH}")
    print(f"  files: {len(names)}")
    print(f"  compressed:   {total_compressed:>9,} bytes")
    print(f"  uncompressed: {total_uncompressed:>9,} bytes\n")
    for n in names:
        print(f"  {n}")
    return OUT_PATH


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
