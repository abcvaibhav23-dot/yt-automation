"""Video rendering for 9:16 YouTube Shorts with subtitle overlays."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

from .subtitle_generator import SubtitleEntry


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


def _create_background_clip(background: Optional[Path], duration: float, size: Tuple[int, int]):
    if not background:
        return ColorClip(size=size, color=(20, 20, 20), duration=duration)

    suffix = background.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return ImageClip(str(background)).resize(newsize=size).set_duration(duration)

    if suffix in {".mp4", ".mov", ".mkv", ".webm"}:
        video = VideoFileClip(str(background)).without_audio().resize(newsize=size)
        if video.duration >= duration:
            return video.subclip(0, duration)

        loops: List[VideoFileClip] = []
        consumed = 0.0
        while consumed < duration:
            part = video.subclip(0, min(video.duration, duration - consumed))
            loops.append(part)
            consumed += part.duration
        return concatenate_videoclips(loops)

    raise ValueError(f"Unsupported background file type: {background.suffix}")


def build_short_video(
    audio_path: Path,
    subtitles: List[SubtitleEntry],
    output_path: Path,
    background_path: Optional[Path] = None,
    size: Tuple[int, int] = (1080, 1920),
    fps: int = 30,
) -> Path:
    """Create a short video with audio and subtitle overlays."""
    audio_clip = AudioFileClip(str(audio_path))
    base = _create_background_clip(background_path, audio_clip.duration, size)

    subtitle_clips = []
    for entry in subtitles:
        subtitle_image = _build_subtitle_image(entry.text, width=size[0])
        subtitle_clip = (
            ImageClip(subtitle_image)
            .set_position(("center", size[1] - 400))
            .set_start(entry.start)
            .set_end(entry.end)
        )
        subtitle_clips.append(subtitle_clip)

    final = CompositeVideoClip([base, *subtitle_clips]).set_audio(audio_clip)
    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        fps=fps,
        threads=4,
        preset="medium",
    )

    final.close()
    audio_clip.close()
    base.close()
    for clip in subtitle_clips:
        clip.close()

    return output_path
