"""Thumbnail extraction and text overlay."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config.settings import FFMPEG_BINARY


def create_thumbnail(video_path: Path, title: str, out_png: Path) -> Path:
    raw_frame = out_png.with_name(out_png.stem + "_raw.png")
    cmd = [FFMPEG_BINARY, "-y", "-i", str(video_path), "-ss", "00:00:12", "-vframes", "1", str(raw_frame)]
    subprocess.run(cmd, check=True, capture_output=True)

    img = Image.open(raw_frame).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([(30, 40), (img.width - 30, 230)], fill=(0, 0, 0, 170))

    words = [w for w in re.sub(r"[^a-zA-Z0-9 ]", "", title).split() if w]
    txt = " ".join(words[:4]).upper() or "DAILY SHORT"
    try:
        f = ImageFont.truetype("Arial.ttf", 72)
    except OSError:
        f = ImageFont.load_default()
    d.text((60, 95), txt, font=f, fill=(255, 255, 255, 255))

    img.save(out_png, format="PNG", optimize=True)
    raw_frame.unlink(missing_ok=True)
    return out_png
