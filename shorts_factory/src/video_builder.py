"""Video rendering for 9:16 YouTube Shorts with subtitle overlays."""
from __future__ import annotations

import hashlib
import math
import shutil
import tempfile
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    VideoFileClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .cinematic_prompt_planner import plan_scene_prompts
from .subtitle_generator import SubtitleEntry
from .visual_provider import resolve_scene_assets

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS


def _build_subtitle_image(text: str, width: int, height: int = 220, font_size: int = 52) -> Image.Image:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    font = None
    for font_name in [
        "NotoSansDevanagari-Bold.ttf",
        "Mukta-Bold.ttf",
        "KohinoorDevanagari-Semibold.otf",
        "Arial Unicode.ttf",
        "Arial.ttf",
    ]:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    margin = 40
    wrapped = "\n".join(textwrap.wrap(text, width=26)[:3]) or text
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center", spacing=8)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) / 2
    y = (height - text_h) / 2

    draw.rounded_rectangle([(margin, 20), (width - margin, height - 20)], radius=24, fill=(0, 0, 0, 160))
    draw.multiline_text(
        (x, y),
        wrapped,
        font=font,
        fill=(255, 255, 255, 255),
        align="center",
        spacing=8,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )
    return image


def _pick_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in [
        "NotoSansDevanagari-Bold.ttf",
        "Mukta-Bold.ttf",
        "KohinoorDevanagari-Semibold.otf",
        "Arial Unicode.ttf",
        "Arial.ttf",
    ]:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _build_title_image(title: str, size: Tuple[int, int]) -> Image.Image:
    width, _ = size
    height = 180
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([(20, 16), (width - 20, height - 16)], radius=26, fill=(0, 0, 0, 150))

    font = _pick_font(54)
    wrapped = "\n".join(textwrap.wrap(title.strip(), width=24)[:2]) or title
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center", spacing=6)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.multiline_text(
        ((width - tw) / 2, (height - th) / 2),
        wrapped,
        font=font,
        fill=(255, 255, 255, 255),
        align="center",
        spacing=6,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )
    return image


def _build_frame_overlay(size: Tuple[int, int]) -> Image.Image:
    width, height = size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    margin = 22
    draw.rounded_rectangle([(margin, margin), (width - margin, height - margin)], radius=40, outline=(255, 255, 255, 200), width=6)
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
    waves = 0.5 + 0.5 * np.sin(2 * np.pi * (x * (1.4 + (seed % 7) * 0.09) + y * 0.8) + phase)
    sweep = np.clip(0.45 + 0.55 * np.cos(2 * np.pi * (y * 0.62) + phase * 0.7), 0, 1)
    r = np.clip(30 + 110 * y + 65 * waves, 0, 255)
    g = np.clip(28 + 92 * (1 - y) + 80 * sweep + 25 * x, 0, 255)
    b = np.clip(62 + 100 * x + 58 * waves, 0, 255)
    image = Image.fromarray(np.dstack([r, g, b]).astype(np.uint8), mode="RGB")

    draw = ImageDraw.Draw(image, "RGBA")
    # Multi-layer blobs to avoid flat backgrounds in offline mode.
    for i in range(7):
        w = int(width * (0.25 + ((seed >> (i + 2)) & 7) * 0.05))
        h = int(height * (0.18 + ((seed >> (i + 5)) & 7) * 0.04))
        px = int((width - w) * ((i * 97 + seed) % 100) / 100)
        py = int((height - h) * ((i * 53 + seed // 2) % 100) / 100)
        tint = (
            120 + (seed + i * 17) % 110,
            90 + (seed + i * 23) % 120,
            110 + (seed + i * 29) % 115,
            46,
        )
        draw.ellipse([(px, py), (px + w, py + h)], fill=tint)

    words = [w for w in text.strip().split() if w]
    cue_words = " ".join(words[:4]).strip() or f"दृश्य {index + 1}"
    cue_words = cue_words[:34]
    top_words = " ".join(words[4:10]).strip()[:48] if len(words) > 4 else cue_words

    draw.rounded_rectangle([(52, 70), (width - 52, 290)], radius=32, fill=(0, 0, 0, 98), outline=(255, 255, 255, 140), width=3)
    title_font = _pick_font(46)
    cue_font = _pick_font(34)
    draw.text((84, 114), f"Scene {index + 1}", font=title_font, fill=(250, 252, 255, 245))
    draw.text((84, 184), top_words or cue_words, font=cue_font, fill=(232, 236, 245, 240))

    # Topic-oriented iconography (simple vector drawings) to keep each scene distinct without external media.
    lower = text.lower()
    icon_x, icon_y = width - 250, 350
    if any(k in lower for k in ["alarm", "late", "sleep", "wake", "morning"]):
        draw.ellipse([(icon_x, icon_y), (icon_x + 170, icon_y + 170)], outline=(255, 255, 255, 210), width=8)
        draw.line([(icon_x + 85, icon_y + 86), (icon_x + 85, icon_y + 40)], fill=(255, 220, 220, 225), width=7)
        draw.line([(icon_x + 85, icon_y + 86), (icon_x + 130, icon_y + 102)], fill=(255, 220, 220, 225), width=7)
    elif any(k in lower for k in ["office", "boss", "meeting", "work"]):
        draw.rounded_rectangle([(icon_x - 10, icon_y), (icon_x + 190, icon_y + 190)], radius=16, fill=(12, 18, 28, 130), outline=(255, 255, 255, 170), width=4)
        for row in range(4):
            for col in range(3):
                wx1 = icon_x + 18 + col * 54
                wy1 = icon_y + 20 + row * 42
                draw.rectangle([(wx1, wy1), (wx1 + 28, wy1 + 20)], fill=(185, 220, 255, 165))
    elif any(k in lower for k in ["phone", "call", "message", "chat"]):
        draw.rounded_rectangle([(icon_x, icon_y), (icon_x + 155, icon_y + 225)], radius=24, fill=(10, 16, 22, 160), outline=(255, 255, 255, 190), width=5)
        draw.rectangle([(icon_x + 25, icon_y + 34), (icon_x + 130, icon_y + 150)], fill=(120, 210, 255, 120))
        draw.ellipse([(icon_x + 66, icon_y + 176), (icon_x + 88, icon_y + 198)], fill=(255, 255, 255, 210))
    else:
        draw.rounded_rectangle([(icon_x - 12, icon_y - 8), (icon_x + 210, icon_y + 176)], radius=20, fill=(10, 18, 28, 120), outline=(255, 255, 255, 160), width=4)
        draw.polygon(
            [(icon_x + 20, icon_y + 138), (icon_x + 72, icon_y + 80), (icon_x + 122, icon_y + 120), (icon_x + 168, icon_y + 64)],
            fill=(255, 206, 80, 180),
        )

    # Bottom-right cue chip for subtitle/scene alignment.
    cue_bbox = draw.textbbox((0, 0), cue_words, font=cue_font)
    cue_w = max(210, cue_bbox[2] - cue_bbox[0] + 40)
    cue_h = max(62, cue_bbox[3] - cue_bbox[1] + 24)
    cx2 = width - 46
    cy2 = height - 66
    cx1 = cx2 - cue_w
    cy1 = cy2 - cue_h
    draw.rounded_rectangle([(cx1, cy1), (cx2, cy2)], radius=18, fill=(0, 0, 0, 120), outline=(255, 255, 255, 132), width=2)
    draw.text((cx1 + 18, cy1 + 10), cue_words, font=cue_font, fill=(245, 248, 255, 235))

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
        p = min(1.0, max(0.0, t / duration))
        x = int(delta_x * p)
        y = int(delta_y * (0.2 + 0.8 * p))
        return arr[y : y + height, x : x + width]

    return VideoClip(make_frame=make_frame, duration=duration).set_start(start).set_end(end)


def _make_cinematic_fx_clip(text: str, size: Tuple[int, int], start: float, end: float) -> VideoClip:
    width, height = size
    duration = max(0.2, end - start)
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    hue_shift = (seed % 70) / 100.0

    def make_frame(t: float):
        p = min(1.0, max(0.0, t / duration))
        x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
        y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
        drift = np.sin(2 * np.pi * (x * (1.4 + hue_shift) + p * 0.8))
        shimmer = np.cos(2 * np.pi * (y * 1.1 - p * (0.9 + hue_shift)))
        glow = np.clip(0.35 + 0.65 * ((drift + shimmer) / 2.0 + 1.0) / 2.0, 0, 1)
        r = np.clip(25 + 45 * glow + 18 * (1 - y), 0, 255)
        g = np.clip(35 + 62 * glow + 30 * x, 0, 255)
        b = np.clip(52 + 80 * glow + 10 * y, 0, 255)
        return np.dstack([r, g, b]).astype(np.uint8)

    return VideoClip(make_frame=make_frame, duration=duration).set_start(start).set_end(end).set_opacity(0.2)


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

    if background.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        return ImageClip(str(background)).resize(newsize=size).set_duration(duration)
    if background.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
        return _make_video_scene_clip(video_path=background, size=size, start=0.0, end=duration)
    raise ValueError(f"Unsupported background file type: {background.suffix}")


def _build_scene_clips(
    subtitles: List[SubtitleEntry],
    style: str,
    region: Optional[str],
    size: Tuple[int, int],
    cache_dir: Path,
    use_external_assets: bool = True,
) -> tuple[List[VideoClip], int]:
    scene_clips: List[VideoClip] = []
    external_scene_count = 0

    scene_assets = []
    if use_external_assets:
        prompts = plan_scene_prompts(subtitles=subtitles, style=style, region=region)
        scene_assets = resolve_scene_assets(prompts=prompts, cache_dir=cache_dir)

    for idx, entry in enumerate(subtitles):
        asset = scene_assets[idx] if idx < len(scene_assets) else None
        if asset is not None and asset.kind == "video":
            scene_clips.append(_make_video_scene_clip(asset.path, size=size, start=entry.start, end=entry.end))
            external_scene_count += 1
        elif asset is not None and asset.kind == "image":
            scene_clips.append(_make_ken_burns_clip(asset.path, size=size, start=entry.start, end=entry.end))
            external_scene_count += 1
        else:
            synth = _synthesize_scene_image(entry.text, idx, cache_dir=cache_dir, size=size)
            scene_clips.append(_make_ken_burns_clip(synth, size=size, start=entry.start, end=entry.end))

        scene_clips.append(_make_cinematic_fx_clip(entry.text, size=size, start=entry.start, end=entry.end))

    return scene_clips, external_scene_count


def build_short_video(
    audio_path: Path,
    subtitles: List[SubtitleEntry],
    output_path: Path,
    background_path: Optional[Path] = None,
    ai_visuals: bool = False,
    assets_dir: Optional[Path] = None,
    style: str = "regional",
    region: Optional[str] = None,
    audio_mode: str = "both",
    bg_music_path: Optional[Path] = None,
    video_title: Optional[str] = None,
    voice_volume: float = 1.0,
    bgm_volume: float = 0.20,
    min_external_scene_ratio: float = 0.0,
    size: Tuple[int, int] = (1080, 1920),
    fps: int = 60,
) -> Path:
    """Create a short video with audio and subtitle overlays."""
    voice_audio = AudioFileClip(str(audio_path))
    duration = voice_audio.duration
    base = _create_background_clip(background_path, duration, size)
    temp_cache = Path(tempfile.mkdtemp(prefix="shorts_scene_"))

    scene_clips: List[VideoClip] = []
    scene_clips, external_scene_count = _build_scene_clips(
        subtitles=subtitles,
        style=style,
        region=region,
        size=size,
        cache_dir=temp_cache,
        use_external_assets=ai_visuals,
    )
    total_scenes = max(1, len(subtitles))
    external_ratio = external_scene_count / total_scenes
    if min_external_scene_ratio > 0 and external_ratio < min_external_scene_ratio:
        for clip in scene_clips:
            clip.close()
        shutil.rmtree(temp_cache, ignore_errors=True)
        raise ValueError(
            f"External scene coverage too low ({external_scene_count}/{total_scenes} = {external_ratio:.0%}). "
            f"Required >= {min_external_scene_ratio:.0%}. Check Pexels/Pixabay network/API key."
        )

    subtitle_clips: List[VideoClip] = []
    for entry in subtitles:
        subtitle_image = _build_subtitle_image(entry.text, width=size[0])
        subtitle_clips.append(
            ImageClip(np.array(subtitle_image)).set_position(("center", size[1] - 400)).set_start(entry.start).set_end(entry.end)
        )

    frame_overlay = ImageClip(np.array(_build_frame_overlay(size))).set_duration(duration).set_position(("center", "center"))
    title_clip = None
    if video_title:
        title_img = _build_title_image(video_title, size=size)
        title_clip = ImageClip(np.array(title_img)).set_duration(duration).set_position(("center", 80))

    mixed_audio = None
    music_audio = None
    if audio_mode in {"voice", "both"}:
        mixed_audio = voice_audio.volumex(max(0.0, voice_volume))

    if audio_mode in {"music", "both"} and bg_music_path is not None:
        music_audio = AudioFileClip(str(bg_music_path))
        if music_audio.duration < duration:
            loops = int(duration // music_audio.duration) + 1
            loop_parts = [music_audio] * loops
            music_audio = concatenate_audioclips(loop_parts)
        music_audio = music_audio.subclip(0, duration).volumex(max(0.0, bgm_volume))
        mixed_audio = music_audio if mixed_audio is None else CompositeAudioClip([mixed_audio, music_audio])

    layers = [base, *scene_clips, *subtitle_clips, frame_overlay]
    if title_clip is not None:
        layers.append(title_clip)
    final = CompositeVideoClip(layers).set_audio(mixed_audio)
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
    voice_audio.close()
    if music_audio is not None:
        music_audio.close()
    base.close()
    frame_overlay.close()
    if title_clip is not None:
        title_clip.close()
    for clip in scene_clips:
        clip.close()
    for clip in subtitle_clips:
        clip.close()
    shutil.rmtree(temp_cache, ignore_errors=True)

    return output_path
