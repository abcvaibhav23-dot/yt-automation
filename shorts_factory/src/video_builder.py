"""Video rendering for 9:16 YouTube Shorts with subtitle overlays."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from moviepy.editor import AudioFileClip, CompositeVideoClip, ImageClip, VideoClip, VideoFileClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .subtitle_generator import SubtitleEntry
from .visual_provider import SceneAsset, resolve_scene_assets, write_usage_report


def _build_subtitle_image(
    text: str,
    width: int,
    height: int = 220,
    font_size: int = 52,
) -> Image.Image:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("Arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    margin = 40
    bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (width - text_w) / 2
    y = (height - text_h) / 2

    draw.rounded_rectangle(
        [(margin, 20), (width - margin, height - 20)],
        radius=24,
        fill=(0, 0, 0, 160),
    )
    draw.multiline_text((x, y), text, font=font, fill=(255, 255, 255, 255), align="center")
    return image


def _build_story_card(text: str, size: Tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    card_w = int(width * 0.86)
    card_h = int(height * 0.48)
    card_x = (width - card_w) // 2
    card_y = int(height * 0.18)

    draw.rounded_rectangle(
        [(card_x, card_y), (card_x + card_w, card_y + card_h)],
        radius=42,
        fill=(250, 248, 241, 235),
        outline=(255, 255, 255, 255),
        width=4,
    )

    band_h = int(card_h * 0.18)
    draw.rounded_rectangle(
        [(card_x + 24, card_y + 24), (card_x + card_w - 24, card_y + 24 + band_h)],
        radius=26,
        fill=(38, 63, 88, 230),
    )

    try:
        title_font = ImageFont.truetype("Arial.ttf", 48)
        body_font = ImageFont.truetype("Arial.ttf", 56)
    except OSError:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()

    draw.text((card_x + 48, card_y + 42), "REGIONAL UPDATE", font=title_font, fill=(255, 255, 255, 255))

    words = text.split()
    lines: List[str] = []
    line: List[str] = []
    for word in words:
        line.append(word)
        if len(" ".join(line)) > 28:
            lines.append(" ".join(line[:-1]))
            line = [word]
    if line:
        lines.append(" ".join(line))
    wrapped = "\n".join(lines[:4])

    body_margin = 58
    draw.multiline_text(
        (card_x + body_margin, card_y + band_h + 70),
        wrapped,
        font=body_font,
        fill=(20, 27, 37, 255),
        spacing=10,
    )
    return image


def _build_frame_overlay(size: Tuple[int, int]) -> Image.Image:
    width, height = size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    margin = 22
    draw.rounded_rectangle(
        [(margin, margin), (width - margin, height - margin)],
        radius=40,
        outline=(255, 255, 255, 200),
        width=6,
    )
    return overlay


def _synthesize_scene_image(text: str, index: int, cache_dir: Path, size: Tuple[int, int]) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{text}-{index}".encode("utf-8")).hexdigest()[:12]
    out = cache_dir / f"synth_{index:03}_{key}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return out

    width, height = size
    seed = int(hashlib.sha256(f"{text}-{index}".encode("utf-8")).hexdigest()[:8], 16)
    phase = (seed % 360) * math.pi / 180.0

    x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    waves = 0.5 + 0.5 * np.sin(2 * np.pi * (x * (1.6 + (seed % 5) * 0.12) + y * 0.9) + phase)
    sweep = np.clip(0.45 + 0.55 * np.cos(2 * np.pi * (y * 0.75) + phase * 0.8), 0, 1)
    r = np.clip(38 + 120 * y + 70 * waves, 0, 255)
    g = np.clip(26 + 95 * (1 - y) + 85 * sweep + 35 * x, 0, 255)
    b = np.clip(58 + 100 * x + 65 * waves, 0, 255)
    base = np.dstack([r, g, b]).astype(np.uint8)
    image = Image.fromarray(base, mode="RGB")

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        [(60, 70), (width - 60, 260)],
        radius=32,
        fill=(0, 0, 0, 90),
        outline=(255, 255, 255, 140),
        width=3,
    )
    try:
        title_font = ImageFont.truetype("Arial.ttf", 56)
        subtitle_font = ImageFont.truetype("Arial.ttf", 44)
    except OSError:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()

    draw.text((95, 105), "AI VISUAL SCENE", font=title_font, fill=(245, 248, 255, 235))
    short_text = " ".join(text.split()[:8]).strip()
    if short_text:
        draw.text((95, 180), short_text, font=subtitle_font, fill=(220, 235, 255, 230))

    image = image.filter(ImageFilter.GaussianBlur(radius=0.25))
    image.save(out, quality=95, optimize=True)
    return out


def _make_ken_burns_clip(image_path: Path, size: Tuple[int, int], start: float, end: float) -> VideoClip:
    width, height = size
    with Image.open(image_path) as img:
        base = img.convert("RGB")
    oversized = ImageOps.fit(base, (int(width * 1.15), int(height * 1.15)), method=Image.Resampling.LANCZOS)
    arr = np.array(oversized)
    big_h, big_w = arr.shape[:2]
    delta_x = max(0, big_w - width)
    delta_y = max(0, big_h - height)
    duration = max(0.2, end - start)

    def make_frame(t: float):
        progress = min(1.0, max(0.0, t / duration))
        x = int(delta_x * progress)
        y = int(delta_y * (0.2 + 0.8 * progress))
        return arr[y : y + height, x : x + width]

    return VideoClip(make_frame=make_frame, duration=duration).set_start(start).set_end(end)


def _make_cinematic_fx_clip(text: str, size: Tuple[int, int], start: float, end: float) -> VideoClip:
    width, height = size
    duration = max(0.2, end - start)
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    hue_shift = (seed % 70) / 100.0

    def make_frame(t: float):
        progress = min(1.0, max(0.0, t / duration))
        x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
        y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
        drift = np.sin(2 * np.pi * (x * (1.4 + hue_shift) + progress * 0.8))
        shimmer = np.cos(2 * np.pi * (y * 1.1 - progress * (0.9 + hue_shift)))
        glow = np.clip(0.35 + 0.65 * ((drift + shimmer) / 2.0 + 1.0) / 2.0, 0, 1)
        r = np.clip(25 + 45 * glow + 18 * (1 - y), 0, 255)
        g = np.clip(35 + 62 * glow + 30 * x, 0, 255)
        b = np.clip(52 + 80 * glow + 10 * y, 0, 255)
        return np.dstack([r, g, b]).astype(np.uint8)

    return VideoClip(make_frame=make_frame, duration=duration).set_start(start).set_end(end).set_opacity(0.20)


def _fit_video_to_vertical(clip: VideoFileClip, size: Tuple[int, int]) -> VideoFileClip:
    target_w, target_h = size
    target_ratio = target_w / target_h
    source_ratio = clip.w / clip.h

    if source_ratio > target_ratio:
        resized = clip.resize(height=target_h)
        return resized.crop(x_center=resized.w / 2, width=target_w)

    resized = clip.resize(width=target_w)
    return resized.crop(y_center=resized.h / 2, height=target_h)


def _make_video_scene_clip(video_path: Path, size: Tuple[int, int], start: float, end: float) -> VideoClip:
    duration = max(0.2, end - start)
    source = VideoFileClip(str(video_path)).without_audio()
    fitted = _fit_video_to_vertical(source, size=size)

    if fitted.duration >= duration:
        segment = fitted.subclip(0, duration)
    else:
        loops: List[VideoClip] = []
        consumed = 0.0
        while consumed < duration:
            part = fitted.subclip(0, min(fitted.duration, duration - consumed))
            loops.append(part)
            consumed += part.duration
        segment = concatenate_videoclips(loops).subclip(0, duration)

    return segment.set_start(start).set_end(end)


def _create_background_clip(background: Optional[Path], duration: float, size: Tuple[int, int]) -> VideoClip:
    if not background:
        width, height = size

        def make_frame(t: float):
            x = np.linspace(0, 1, width)
            y = np.linspace(0, 1, height)[:, None]
            wave = 0.5 + 0.5 * np.sin(2 * np.pi * (x[None, :] * 1.7 + t * 0.06))
            r = np.clip(18 + 58 * y + 42 * wave, 0, 255)
            g = np.clip(24 + 64 * (1 - y) + 34 * wave, 0, 255)
            b = np.clip(44 + 52 * (1 - y) + 84 * x[None, :] + 18 * wave, 0, 255)
            return np.dstack([r, g, b]).astype(np.uint8)

        return VideoClip(make_frame=make_frame, duration=duration)

    suffix = background.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return ImageClip(str(background)).resize(newsize=size).set_duration(duration)

    if suffix in {".mp4", ".mov", ".mkv", ".webm"}:
        return _make_video_scene_clip(video_path=background, size=size, start=0.0, end=duration)

    raise ValueError(f"Unsupported background file type: {background.suffix}")


def _build_scene_clips(
    subtitles: List[SubtitleEntry],
    size: Tuple[int, int],
    assets_dir: Path,
    output_path: Path,
) -> List[VideoClip]:
    scene_assets = resolve_scene_assets(subtitles=subtitles, assets_dir=assets_dir)
    used_assets: List[SceneAsset] = []
    scene_clips: List[VideoClip] = []

    for idx, entry in enumerate(subtitles):
        asset = scene_assets[idx] if idx < len(scene_assets) else None
        if asset is not None and asset.kind == "video":
            clip = _make_video_scene_clip(asset.path, size=size, start=entry.start, end=entry.end)
            scene_clips.append(clip)
            used_assets.append(asset)
        elif asset is not None and asset.kind == "image":
            scene_clips.append(_make_ken_burns_clip(asset.path, size=size, start=entry.start, end=entry.end))
            used_assets.append(asset)
        else:
            synth = _synthesize_scene_image(entry.text, idx, cache_dir=assets_dir / "scene_cache", size=size)
            scene_clips.append(_make_ken_burns_clip(synth, size=size, start=entry.start, end=entry.end))

        scene_clips.append(_make_cinematic_fx_clip(entry.text, size=size, start=entry.start, end=entry.end))

    if used_assets:
        write_usage_report(used_assets, output_path.with_suffix(".credits.txt"))
    else:
        output_path.with_suffix(".credits.txt").write_text(
            "No external provider media used.\n"
            "All scene visuals were locally synthesized for this run.\n"
            "Configure PEXELS_API_KEY and/or PIXABAY_API_KEY for royalty-free source media.\n",
            encoding="utf-8",
        )
    return scene_clips


def build_short_video(
    audio_path: Path,
    subtitles: List[SubtitleEntry],
    output_path: Path,
    background_path: Optional[Path] = None,
    ai_visuals: bool = False,
    assets_dir: Optional[Path] = None,
    size: Tuple[int, int] = (1080, 1920),
    fps: int = 60,
) -> Path:
    """Create a short video with audio and subtitle overlays."""
    audio_clip = AudioFileClip(str(audio_path))
    base = _create_background_clip(background_path, audio_clip.duration, size)

    scene_clips: List[VideoClip] = []
    if ai_visuals and assets_dir is not None:
        scene_clips = _build_scene_clips(subtitles=subtitles, size=size, assets_dir=assets_dir, output_path=output_path)

    card_clips: List[VideoClip] = []
    if not scene_clips:
        for entry in subtitles:
            card_image = _build_story_card(entry.text, size=size)
            card_clip = (
                ImageClip(np.array(card_image))
                .set_start(entry.start)
                .set_end(entry.end)
                .set_position(("center", "center"))
                .crossfadein(0.15)
                .crossfadeout(0.15)
            )
            card_clips.append(card_clip)

    subtitle_clips: List[VideoClip] = []
    for entry in subtitles:
        subtitle_image = _build_subtitle_image(entry.text, width=size[0])
        subtitle_clip = (
            ImageClip(np.array(subtitle_image))
            .set_position(("center", size[1] - 400))
            .set_start(entry.start)
            .set_end(entry.end)
        )
        subtitle_clips.append(subtitle_clip)

    frame_overlay = ImageClip(np.array(_build_frame_overlay(size))).set_duration(audio_clip.duration).set_position(("center", "center"))

    final = CompositeVideoClip([base, *scene_clips, *card_clips, *subtitle_clips, frame_overlay]).set_audio(audio_clip)
    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        fps=fps,
        threads=4,
        preset="slow",
        bitrate="10M",
        audio_bitrate="192k",
        ffmpeg_params=["-crf", "16", "-pix_fmt", "yuv420p"],
    )

    final.close()
    audio_clip.close()
    base.close()
    frame_overlay.close()
    for clip in scene_clips:
        clip.close()
    for clip in card_clips:
        clip.close()
    for clip in subtitle_clips:
        clip.close()

    return output_path
