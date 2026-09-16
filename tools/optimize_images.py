#!/usr/bin/env python3
"""
Generate the modern-format variants of every post image, and report their
real pixel size (which is what the build writes into width=/height= so the
browser can reserve the space before the bytes arrive).

For each `images/NN-name.jpg` (or .png) this writes two siblings:

  images/NN-name.webp    WebP,   ~45% smaller than the JPG
  images/NN-name.avif    AVIF,   ~70% smaller than the JPG

The JPG is kept: it is the `<img src>` fallback inside the post's `<picture>`,
so browsers without AVIF/WebP still get the picture, and Blogger still finds a
`data:post.featuredImage` for the home-page cards.

Nothing is uploaded anywhere - the images are served straight out of this repo
by jsDelivr, so "compress the asset" and "commit the asset" are the same step.

Usage:
  python3 tools/optimize_images.py                 # every post
  python3 tools/optimize_images.py <folder>        # one post (name or path)
  python3 tools/optimize_images.py --check         # report drift, write nothing
  python3 tools/optimize_images.py --json          # machine-readable size map

Requires ImageMagick (`convert`) with WEBP + AVIF delegates, which is what
`convert -list format | grep -E 'WEBP|AVIF'` shows. Without it this prints a
warning and exits 0 - the build still works, the posts just keep serving JPGs.

Exit status: 0 = everything current, 1 = a variant is missing or stale
(only ever set by --check).
"""

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "posts"

# Quality is deliberately below "visually lossless" and above "banding": these
# are illustrations and screenshots, which show artefacts earlier than photos.
WEBP_QUALITY = os.environ.get("WEBP_QUALITY", "82")
AVIF_QUALITY = os.environ.get("AVIF_QUALITY", "62")
BASE_EXT = {".jpg", ".jpeg", ".png"}
VARIANTS = (("webp", WEBP_QUALITY), ("avif", AVIF_QUALITY))


# ---------------------------------------------------------------------------
# pixel size, with no dependency beyond the standard library
# ---------------------------------------------------------------------------

def _png_size(d: bytes):
    if d[:8] == b"\x89PNG\r\n\x1a\n" and d[12:16] == b"IHDR":
        return struct.unpack(">II", d[16:24])
    return None


def _gif_size(d: bytes):
    if d[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", d[6:10])
        return w, h
    return None


def _jpeg_size(d: bytes):
    if d[:3] != b"\xff\xd8\xff":
        return None
    i = 2
    while i < len(d) - 9:
        if d[i] != 0xFF:
            i += 1
            continue
        marker = d[i + 1]
        # SOF0..SOF15 except DHT/JPG/DAC: the frame header carries the size
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", d[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
    return None


def _webp_size(d: bytes):
    if d[:4] != b"RIFF" or d[8:12] != b"WEBP":
        return None
    chunk, body = d[12:16], d[16:]
    if chunk == b"VP8X":
        w = 1 + int.from_bytes(body[4:7], "little")
        h = 1 + int.from_bytes(body[7:10], "little")
        return w, h
    if chunk == b"VP8 ":
        return struct.unpack("<HH", body[6:10])[0] & 0x3FFF, struct.unpack("<HH", body[6:10])[1] & 0x3FFF
    if chunk == b"VP8L":
        b0, b1, b2, b3 = body[1], body[2], body[3], body[4]
        return 1 + ((b1 & 0x3F) << 8 | b0), 1 + ((b3 & 0x0F) << 10 | b2 << 2 | (b1 & 0xC0) >> 6)
    return None


def _avif_size(d: bytes):
    """Walk the ISOBMFF boxes to the first `ispe` (image spatial extents)."""
    i = d.find(b"ispe")
    if i < 0 or i + 12 > len(d):
        return None
    return struct.unpack(">II", d[i + 8:i + 16])


_READERS = ((_png_size, 4096), (_gif_size, 16), (_jpeg_size, 1 << 20), (_webp_size, 64), (_avif_size, 1 << 20))


def pixel_size(path: Path):
    """(width, height) of an image file, or None if the format is unknown."""
    try:
        with open(path, "rb") as f:
            head = f.read(1 << 20)          # JPEG markers can sit far in
    except OSError:
        return None
    for reader, need in _READERS:
        if len(head) >= min(need, 16):
            got = reader(head)
            if got:
                return got
    return None


def identify(path: Path):
    """pixel_size(), falling back to ImageMagick for exotic formats."""
    got = pixel_size(path)
    if got:
        return got
    exe = shutil.which("identify")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-format", "%w %h", str(path)],
                             capture_output=True, text=True, timeout=60).stdout.split()
        return int(out[0]), int(out[1])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# conversion
# ---------------------------------------------------------------------------

def converter():
    for name in ("magick", "convert"):
        exe = shutil.which(name)
        if exe:
            return [exe] if name == "convert" else [exe, "convert"]
    return None


def supported(cmd) -> dict:
    """{'webp': bool, 'avif': bool} for the installed ImageMagick."""
    if not cmd:
        return {}
    argv = cmd + ["-list", "format"]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return {}
    ok = {}
    for fmt in ("webp", "avif"):
        m = re.search(rf"^\s*{fmt.upper()}\S*\s+\S*\s+([-a-z+]+)", out, re.I | re.M)
        ok[fmt] = bool(m and ("w" in m.group(1)))
    return ok


def make_variant(src: Path, dst: Path, fmt: str, quality: str, cmd) -> bool:
    if fmt == "webp":
        argv = cmd + [str(src), "-quality", quality, "-define", "webp:method=6", str(dst)]
    else:
        # speed=6 keeps the encode in seconds instead of minutes per image
        argv = cmd + [str(src), "-quality", quality, "-define", "avif:speed=6", str(dst)]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    except Exception as e:                                     # pragma: no cover
        print(f"   WARN    could not encode {dst.name}: {e}")
        return False
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        print(f"   WARN    could not encode {dst.name}: {(r.stderr or r.stdout).strip()[:160]}")
        dst.unlink(missing_ok=True)
        return False
    return True


def kb(n: int) -> str:
    return f"{n / 1024:.1f}K"


# ---------------------------------------------------------------------------

def post_folders(one=None) -> list:
    if one:
        p = Path(one)
        return [p if p.is_dir() else POSTS_DIR / one]
    return sorted(d for d in POSTS_DIR.iterdir() if d.is_dir() and not d.name.startswith("_"))


def scan(folder: Path) -> list:
    """[{base, src, variants:[{ext,path,quality}]}] for one post's images/."""
    img_dir = folder / "images"
    if not img_dir.is_dir():
        return []
    out = []
    for src in sorted(img_dir.iterdir()):
        if not src.is_file() or src.suffix.lower() not in BASE_EXT:
            continue
        out.append({
            "base": src.with_suffix("").name,
            "src": src,
            "variants": [{"ext": e, "path": src.with_suffix("." + e), "quality": q} for e, q in VARIANTS],
        })
    return out


def run(folder: Path, check: bool, cmd, ok: dict) -> int:
    entries = scan(folder)
    if not entries:
        return 0
    stale = 0
    print(f"posts/{folder.name}/images/")
    for e in entries:
        src = e["src"]
        size = identify(src)
        head = f"   {src.name:52s} {kb(src.stat().st_size):>7s}"
        head += f"  {size[0]}x{size[1]}" if size else "  ?x?"
        print(head)
        for v in e["variants"]:
            if not ok.get(v["ext"]):
                print(f"      skip .{v['ext']} - this ImageMagick cannot write it")
                continue
            fresh = v["path"].exists() and v["path"].stat().st_mtime >= src.stat().st_mtime
            if check:
                if not v["path"].exists():
                    print(f"      MISS .{v['ext']} not generated yet")
                    stale += 1
                elif not fresh:
                    print(f"      STALE .{v['ext']} is older than {src.name}")
                    stale += 1
                else:
                    saved = 100 - 100 * v["path"].stat().st_size / src.stat().st_size
                    print(f"      ok   .{v['ext']} {kb(v['path'].stat().st_size):>7s}  (-{saved:.0f}%)")
                continue
            if fresh:
                saved = 100 - 100 * v["path"].stat().st_size / src.stat().st_size
                print(f"      keep .{v['ext']} {kb(v['path'].stat().st_size):>7s}  (-{saved:.0f}%)")
                continue
            if make_variant(src, v["path"], v["ext"], v["quality"], cmd):
                saved = 100 - 100 * v["path"].stat().st_size / src.stat().st_size
                print(f"      wrote .{v['ext']} {kb(v['path'].stat().st_size):>7s}  (-{saved:.0f}%)")
            else:
                stale += 1
    return stale


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate WebP/AVIF variants of the post images")
    ap.add_argument("post", nargs="?", help="post folder name or path (default: all)")
    ap.add_argument("--check", action="store_true", help="report missing/stale variants, write nothing")
    ap.add_argument("--json", action="store_true", help="print {file: [width, height, bytes]} and exit")
    a = ap.parse_args()

    folders = post_folders(a.post)

    if a.json:
        out = {}
        for f in folders:
            for e in scan(f):
                paths = [e["src"]] + [v["path"] for v in e["variants"] if v["path"].exists()]
                for p in paths:
                    sz = identify(p)
                    out[f"posts/{f.name}/images/{p.name}"] = [sz[0], sz[1], p.stat().st_size] if sz else [None, None, p.stat().st_size]
        print(json.dumps(out, indent=2))
        return 0

    cmd = converter()
    if not cmd:
        print("WARN  ImageMagick not found - install it (apt install imagemagick) to encode WebP/AVIF.")
        print("      The posts keep working: the JPG fallback is already in place.")
        return 0
    ok = supported(cmd)
    if not any(ok.values()):
        print("WARN  this ImageMagick writes neither WebP nor AVIF (`convert -list format`).")
        print("      On Debian/Ubuntu: apt install webp libheif-examples, or rebuild with the delegates.")
        return 0

    stale = sum(run(f, a.check, cmd, ok) for f in folders)
    if a.check and stale:
        print(f"\n{stale} image variant(s) missing or stale - run: python3 tools/optimize_images.py")
        return 1
    if not a.check:
        print("\nCommit the .webp/.avif files next to their .jpg: they are served straight from")
        print("this repo by jsDelivr, so the post's <picture> only works once they are on main.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
