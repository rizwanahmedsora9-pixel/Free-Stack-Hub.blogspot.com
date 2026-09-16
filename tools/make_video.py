#!/usr/bin/env python3
"""
Turn a post folder into shareable videos: portrait (1080x1920) for Shorts/Reels/TikTok
and landscape (1920x1080) for YouTube/X, built from the post's own images and text.

  python3 tools/make_video.py posts/2026-09-16-my-post --dry-run   # storyboard only
  python3 tools/make_video.py posts/2026-09-16-my-post              # both sizes
  python3 tools/make_video.py 2026-09-16-my-post --size portrait
  python3 tools/make_video.py 2026-09-16-my-post --silent          # no narration
  python3 tools/make_video.py 2026-09-16-my-post --reuse-storyboard # keep edited copy

How it works
  1. parse post.html -> storyboard: hook card (feature image + the 2-4 sentence hook),
     one card per <h2> after the jump break, then a recap/CTA card. Written to
     video/storyboard.json; edit "voiceover" or "subtitle" there and re-run with
     --reuse-storyboard to change what the video says without touching the post.
  2. narration: video/narration/01.mp3, 02.mp3, ... one clip per card, in card order.
     Each card is timed to its own clip, so audio and subtitles never drift.
     Missing clips fall back to word-count timing and silent padding - it still renders.
  3. frames: PIL composites the card image, the title, and one burned-in subtitle per
     caption chunk (DejaVu fonts, no fontconfig needed).
  4. encode: ffmpeg concat of those frames, muxed with the concatenated narration.

Needs pillow and an ffmpeg binary - system ffmpeg, or
  python3 -m pip install --break-system-packages imageio-ffmpeg
which ships a static ffmpeg with libx264 + aac and is found automatically.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_import import BLOG_URL, TAG_RE, load_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLOG_NAME = "Free Stack Hub"
BLOG_HOST = BLOG_URL.split("//")[-1].rstrip("/")  # host, not the display name
ACCENT = (56, 189, 248)
INK = (248, 250, 252)
MUTED = (148, 163, 184)
SIZES = {"portrait": (1080, 1920), "landscape": (1920, 1080)}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac"}
CAPTION_CHARS = 92


# --------------------------------------------------------------------------- ffmpeg

_FFMPEG = None


def ffmpeg_exe() -> str:
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    if shutil.which("ffmpeg"):
        _FFMPEG = "ffmpeg"
    else:
        try:
            import imageio_ffmpeg

            _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            sys.exit(
                "no ffmpeg found: install it (apt-get install ffmpeg) or run\n"
                "  python3 -m pip install --break-system-packages imageio-ffmpeg"
            )
    return _FFMPEG


def run(cmd: list) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("command failed:\n  " + " ".join(str(c) for c in cmd) + "\n" + r.stderr[-1500:])
    return r.stdout + r.stderr


def media_duration(path: Path) -> float:
    """Seconds, read from ffmpeg's own banner (this static build has no ffprobe).
    ffmpeg exits non-zero when given an input and no output, so read stderr anyway."""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if not m:
        raise RuntimeError(f"could not read the duration of {path}")
    h, mnt, sec = m.groups()
    d = int(h) * 3600 + int(mnt) * 60 + float(sec)
    start = re.search(r"start:\s*(-?[\d.]+)", out)
    return max(0.2, d - float(start.group(1)) if start else d)


def silence(path: Path, seconds: float) -> None:
    run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{seconds:.3f}", "-c:a", "aac", "-b:a", "96k", str(path)])


def concat_audio(clips: list, dst: Path) -> None:
    n = len(clips)
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    norm = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    labels = "".join(f"[{i}:a]{norm}[a{i}];" for i in range(n))
    cmd += ["-filter_complex", labels + "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]",
            "-map", "[out]", "-c:a", "aac", "-b:a", "168k", "-ar", "44100", str(dst)]
    run(cmd)


# --------------------------------------------------------------------- post -> cards

def sentences(html: str) -> list:
    text = " ".join(TAG_RE.sub(" ", html).split())
    for a, b in (("&rarr;", "->"), ("&amp;", "&"), ("&nbsp;", " "), ("&quot;", '"')):
        text = text.replace(a, b)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def blocks(html: str, tag: str) -> list:
    return re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}\s*>", html, re.S | re.I)


def images_in(html: str) -> list:
    return [m.split("/")[-1].strip('"') for m in re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', html, re.I)]


def storyboard_from_post(post: dict, max_cards: int) -> list:
    """Hook card, one card per section, recap card. Voiceover stays deliberately short:
    a teaser sells the click, it does not re-read the article."""
    body = post["html"]
    teaser = post.get("teaser") or body
    hook = sentences("".join(f"<p>{x}</p>" for x in blocks(teaser, "p")))
    feature = (images_in(teaser) or images_in(body) or [None])[0]

    cards = [{
        "kind": "hook",
        "image": feature,
        "eyebrow": f"{BLOG_NAME} \u00b7 {post['published'].strftime('%d %b %Y')}",
        "title": post["title"],
        "voiceover": " ".join(hook[:4]),
    }]

    sections = []
    for chunk in re.split(r"<h2\b[^>]*>", body, flags=re.I)[1:]:
        head, _, rest = chunk.partition("</h2>")
        rest = re.split(r"<h[23]\b", rest, flags=re.I)[0]
        paras = sentences("".join(f"<p>{x}</p>" for x in blocks(rest, "p")))
        if not paras:
            continue
        sections.append({
            "kind": "section",
            "image": (images_in(rest) or [None])[0] or feature,
            "eyebrow": "The post",
            "title": " ".join(TAG_RE.sub(" ", head).split()),
            "voiceover": " ".join(paras[:2]),
        })

    room = max(1, max_cards - 2)  # sections allowed in the deck, merged one included
    if len(sections) > room:  # merge the overflow rather than dropping content
        keep, extra = sections[: room - 1], sections[room - 1:]
        merged = dict(keep[-1]) if keep else {}
        merged.update({
            "kind": "section",
            "image": (extra[0].get("image") or merged.get("image")),
            "eyebrow": "The post",
            "title": f"{extra[0]['title']} (+{len(extra) - 1} more)" if len(extra) > 1 else extra[0]["title"],
            "voiceover": " ".join(s["voiceover"] for s in extra)[:300],
        })
        sections = keep + [merged]

    lists = blocks(body, "ol")
    items = [" ".join(TAG_RE.sub(" ", x).split()) for x in blocks(lists[-1], "li")] if lists else []
    last_para = (sentences("".join(f"<p>{x}</p>" for x in blocks(body, "p"))) or [""])[-1]
    cards += sections
    cards.append({
        "kind": "recap",
        "image": feature,
        "eyebrow": "Quick recap",
        "title": "What to do",
        "voiceover": (" ".join(items[:5]) or last_para)[:300],
        "bullets": items[:5],
        "cta": f"Full walkthrough: {BLOG_HOST}",
    })
    return cards


# ------------------------------------------------------------------------- rendering

def font(size: int, bold: bool = False):
    from PIL import ImageFont

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for cand in (f"/usr/share/fonts/truetype/dejavu/{name}", f"/usr/share/fonts/truetype/{name}", name):
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(draw, text: str, fnt, max_w: int) -> list:
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if not cur or draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def gradient(h: int, w: int):
    from PIL import Image

    g = Image.new("L", (1, h))
    px = g.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = int(55 + 180 * (t ** 1.4))
    return g.resize((w, h))


def cover(img, w: int, h: int):
    from PIL import Image

    s = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    l, t = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))


def backdrop(image_path: Path, w: int, h: int, dim: float):
    from PIL import Image, ImageFilter, ImageOps

    if image_path and image_path.exists():
        bg = cover(Image.open(image_path).convert("RGB"), w, h)
        bg = ImageOps.autocontrast(bg, cutoff=1)
        if dim < 1.0:
            bg = Image.blend(Image.new("RGB", bg.size, (7, 11, 20)), bg, dim)
    else:
        bg = Image.new("RGB", (w, h), (9, 13, 24))
    bg.paste(Image.new("RGB", (w, h), (5, 9, 17)), (0, 0), gradient(h, w))
    return bg


def draw_card(card: dict, size: str, image_dir: Path, subtitle: str = None):
    from PIL import Image, ImageDraw

    w, h = SIZES[size]
    port = size == "portrait"
    m = int(w * (0.075 if port else 0.06))
    blur = card["kind"] != "hook"
    img = backdrop(image_dir / card["image"] if card.get("image") else None, w, h,
                   dim=1.0 if card["kind"] == "hook" else 0.72)
    if blur:
        img = img.filter(ImageFilter_blur(w))
    d = ImageDraw.Draw(img, "RGBA")

    f_eye = font(max(22, int(w * 0.0215)), bold=True)
    f_title = font(int(w * (0.068 if port else 0.052)), bold=True)
    f_body = font(int(w * (0.033 if port else 0.025)))
    f_sub = font(int(w * (0.035 if port else 0.026)), bold=True)

    top = int(h * 0.05)
    d.text((m, top), (card.get("eyebrow") or "").upper(), font=f_eye, fill=ACCENT)
    if card.get("index"):
        d.text((w - m, top), card["index"], font=f_eye, fill=MUTED, anchor="ra")
    d.line([m, top + int(f_eye.size * 1.9), w - m, top + int(f_eye.size * 1.9)], fill=(255, 255, 255, 34), width=1)

    # auto-fit: shrink the title until it fits both the line cap and the space above
    # the subtitle band, instead of silently chopping the last line
    ty = int(h * (0.115 if port else 0.15))
    room = int(h * (0.62 if card["kind"] == "hook" else 0.55 if port else 0.42)) - ty
    cap = 5 if port else 3
    size, lines = f_title.size, []
    for shrink in (1.0, 0.94, 0.88, 0.82, 0.76, 0.7, 0.64, 0.58):
        size = max(28, int(f_title.size * shrink))
        lines = wrap(d, card["title"], font(size, True), w - 2 * m)
        if len(lines) <= cap and len(lines) * int(size * 1.22) <= room:
            break
    f_title = font(size, True)
    if len(lines) > cap:  # still too long: keep the head, mark the cut
        lines = lines[:cap]
        lines[-1] = re.sub(r"\s*\W*$", "", lines[-1]) + "\u2026"
    for ln in lines:
        d.text((m, ty), ln, font=f_title, fill=INK, stroke_width=2, stroke_fill=(3, 7, 14, 200))
        ty += int(f_title.size * 1.22)

    if card.get("bullets"):
        ty += int(h * 0.015)
        for b in card["bullets"]:
            bl = wrap(d, "\u2022  " + re.sub(r"^``|``$", "", b), f_body, w - 2 * m)
            for k, ln in enumerate(bl):
                d.text((m + (0 if k == 0 else int(w * 0.035)), ty), ln, font=f_body,
                       fill=INK if k == 0 else MUTED)
                ty += int(f_body.size * 1.26)
            ty += int(h * 0.005)
        if card.get("cta"):
            ty += int(h * 0.018)
            d.text((m, ty), card["cta"], font=f_eye, fill=ACCENT)

    if subtitle:
        slines = wrap(d, subtitle, f_sub, w - 2 * m - int(w * 0.07))
        line_h = int(f_sub.size * 1.28)
        pad_y, pad_x = int(h * 0.016), int(w * 0.035)
        bh = line_h * len(slines) + pad_y * 2
        y0 = int(h * (0.88 if port else 0.82)) - bh
        d.rounded_rectangle([m - pad_x, y0, w - m + pad_x, y0 + bh], radius=int(w * 0.02),
                             fill=(3, 7, 14, 222), outline=(255, 255, 255, 30), width=1)
        yy = y0 + pad_y
        for ln in slines:
            d.text((w // 2, yy), ln, font=f_sub, fill=(255, 255, 255), anchor="ma")
            yy += line_h
    return img


def ImageFilter_blur(w: int):
    from PIL import ImageFilter

    return ImageFilter.GaussianBlur(1.5 if w < 1200 else 2.5)


# ---------------------------------------------------------------------------- timing

def caption_chunks(text: str) -> list:
    """Split a card's voiceover into subtitle-sized chunks, breaking long sentences."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    out = []
    for s in sentences(f"<p>{text}</p>"):
        if len(s) <= CAPTION_CHARS:
            out.append(s)
            continue
        cur = ""
        for w in s.split():
            if not cur or len(cur) + len(w) + 1 <= CAPTION_CHARS:
                cur = (cur + " " + w).strip()
            else:
                out.append(cur)
                cur = w
        if cur:
            out.append(cur)
    return out


def split_duration(total: float, weights: list) -> list:
    tot = float(sum(weights)) or 1.0
    d = [round(max(0.9, total * w / tot), 3) for w in weights]
    d[-1] = round(d[-1] + max(0.0, total - sum(d)), 3)  # exact sum, no audio drift
    return d


def find_narration(vdir: Path, n: int) -> list:
    d = vdir / "narration"
    out = []
    for i in range(1, n + 1):
        hit = next((p for p in sorted(d.glob(f"{i:02d}.*")) if p.suffix.lower() in AUDIO_EXT), None) if d.exists() else None
        out.append(hit)
    return out


# ------------------------------------------------------------------------------ main

def render(cards: list, durations: list, size: str, vdir: Path, image_dir: Path,
            fps: int, crf: int, audio: Path, out_name: str) -> Path:
    frames = vdir / f"frames_{size}"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True, exist_ok=True)

    lst, idx = [], 0
    for card, durs in zip(cards, durations):
        subs = card["_subs"] or [None]
        for j, dur in enumerate(durs):
            fp = frames / f"f{idx:04d}.png"
            draw_card(card, size, image_dir, subtitle=subs[j] if j < len(subs) else None).save(
                fp, compress_level=6
            )
            lst.append(f"file '{frames.name}/{fp.name}'\nduration {dur}")
            idx += 1
    lst.append(f"file '{frames.name}/f{idx-1:04d}.png'")
    list_file = vdir / f"list_{size}.txt"
    list_file.write_text("\n".join(lst) + "\n", encoding="utf-8")

    dst = vdir / out_name
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-vf", f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-movflags", "+faststart"]
    cmd += ["-c:a", "copy"] if audio else ["-an"]
    cmd += ["-map", "0:v:0"] + (["-map", "1:a:0"] if audio else []) + [str(dst)]
    run(cmd)
    shutil.rmtree(frames, ignore_errors=True)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("post", help="post folder name or path")
    ap.add_argument("--size", choices=["portrait", "landscape", "both"], default="both")
    ap.add_argument("--max-cards", type=int, default=8, help="cap on cards; extra sections get merged")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=21, help="x264 quality: 18 sharp, 21 good, 24 small")
    ap.add_argument("--tail", type=float, default=0.6, help="seconds of breathing room at the end")
    ap.add_argument("--silent", action="store_true", help="ignore narration/ and time cards by word count")
    ap.add_argument("--reuse-storyboard", action="store_true", help="keep an edited video/storyboard.json")
    ap.add_argument("--dry-run", action="store_true", help="write the storyboard and stop")
    a = ap.parse_args()

    folder = Path(a.post)
    folder = folder if folder.is_dir() else ROOT / "posts" / a.post
    post = load_post(folder)
    if post["problems"]:
        for pr in post["problems"]:
            print(f"  ERROR   {pr}")
        sys.exit(f"\nposts/{folder.name}/ does not build cleanly - fix that before making a video.")

    vdir = folder / "video"
    vdir.mkdir(exist_ok=True)
    image_dir = folder / "images"
    sb = vdir / "storyboard.json"

    if a.reuse_storyboard and sb.exists():
        cards = json.loads(sb.read_text(encoding="utf-8"))
        print(f"using the existing storyboard ({len(cards)} cards)")
    else:
        cards = storyboard_from_post(post, a.max_cards)
        if sb.exists():
            # POST_RULES.md section 11 makes storyboard.json the edit surface: the
            # voiceover in it is also the burned-in caption, so it gets hand-tuned
            # and the narration clips are timed to it. Regenerating without
            # --reuse-storyboard silently throws those edits away (and leaves the
            # existing 01.mp3, 02.mp3, ... out of step with the new text), so say so.
            try:
                old = json.loads(sb.read_text(encoding="utf-8"))
            except Exception:                                    # pragma: no cover
                old = []
            edited = [
                o.get("voiceover", "")
                for o, n in zip(old, cards)
                if o.get("voiceover") and o.get("voiceover") != n.get("voiceover")
            ]
            if edited:
                print(f"  WARNING about to overwrite {len(edited)} hand-edited voiceover line(s) in "
                      f"posts/{folder.name}/video/storyboard.json")
                print("          keep them with --reuse-storyboard, or restore afterwards with "
                      f"git checkout -- posts/{folder.name}/video/storyboard.json")
    for i, c in enumerate(cards, 1):
        c["index"] = f"{i:02d} / {len(cards):02d}"
        c["_subs"] = caption_chunks(c.get("subtitle") or c.get("voiceover") or c.get("title"))
    sb.write_text(json.dumps([{k: v for k, v in c.items() if not k.startswith("_")} for c in cards],
                             indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{folder.name}: {len(cards)} card(s) -> posts/{folder.name}/video/storyboard.json")
    for c in cards:
        print(f"  {c['index']}  img={str(c.get('image'))[:34]:34} {c['title'][:52]}")
    if a.dry_run:
        print("\nno render yet: put one narration clip per card in video/narration/ as 01.mp3, 02.mp3, ...")
        return 0

    clips = [None] * len(cards) if a.silent else find_narration(vdir, len(cards))
    found = sum(1 for c in clips if c)
    if not a.silent and found != len(cards):
        print(f"  note     {found}/{len(cards)} narration clips in video/narration/; "
              f"the rest are timed by word count and padded with silence")

    durations, tracks = [], []
    for i, c in enumerate(cards):
        subs = c["_subs"] or [c["title"]]
        if clips[i]:
            total = media_duration(clips[i])
            tracks.append(clips[i])
        else:
            total = 1.2 + 0.05 * len(re.sub(r"\s+", " ", c.get("voiceover") or "").split())
            tracks.append(None)
        durations.append(split_duration(total, [max(18, len(s)) for s in subs]))

    print("\ncard timings")
    for c, d in zip(cards, durations):
        print(f"  {c['index']}  {sum(d):5.1f}s")
    audio = None
    if not a.silent:
        mix = []
        for i, t in enumerate(tracks):
            if t:
                mix.append(t)
            else:  # pad exactly this card's length so later cards stay in sync
                sil = vdir / f"_sil_{i + 1:02d}.m4a"
                silence(sil, sum(durations[i]))
                mix.append(sil)
        audio = vdir / "narration_full.m4a"
        concat_audio(mix, audio)
        durations[-1][-1] += a.tail
        for sp in vdir.glob("_sil_*.m4a"):
            sp.unlink(missing_ok=True)

    out = []
    for size in (["portrait", "landscape"] if a.size == "both" else [a.size]):
        tag = "vertical" if size == "portrait" else "wide"
        dst = render(cards, durations, size, vdir, image_dir, a.fps, a.crf, audio, f"blog-to-video-{tag}.mp4")
        mb = dst.stat().st_size / 1e6
        print(f"  wrote posts/{folder.name}/video/{dst.name}  {mb:.1f} MB  "
              f"{media_duration(dst):.1f}s  {SIZES[size][0]}x{SIZES[size][1]}")
        out.append(dst)
    print("\nBlogger cannot host video: upload the wide one to YouTube and the vertical one to "
          "Shorts/Reels/TikTok, then link it back to the post.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
