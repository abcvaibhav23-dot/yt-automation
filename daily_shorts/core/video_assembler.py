"""Assemble final vertical short video with subtitles and audio mix."""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List

import numpy as np
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

from core.subtitle_engine import SubtitleLine

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS


class VideoAssembler:
    def __init__(self, size=(1080, 1920), fps: int = 30) -> None:
        self.size = size
        self.fps = fps

    def _fit_vertical(self, clip: VideoFileClip) -> VideoFileClip:
        target_w, target_h = self.size
        if clip.w / clip.h > target_w / target_h:
            c = clip.resize(height=target_h)
            return c.crop(x_center=c.w / 2, width=target_w)
        c = clip.resize(width=target_w)
        return c.crop(y_center=c.h / 2, height=target_h)

    def _subtitle_image(self, text: str) -> Image.Image:
        w = self.size[0]
        h = 210
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        try:
            f = ImageFont.truetype("Arial.ttf", 52)
        except OSError:
            f = ImageFont.load_default()
        wrapped = "\n".join(textwrap.wrap(text, width=30)[:2])
        d.rounded_rectangle([(35, 20), (w - 35, h - 20)], radius=24, fill=(0, 0, 0, 150))
        d.multiline_text((75, 62), wrapped, font=f, fill=(255, 255, 255, 255), spacing=8)
        return img

    def _title_image(self, title: str) -> Image.Image:
        w = self.size[0]
        h = 160
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([(20, 12), (w - 20, h - 12)], radius=20, fill=(0, 0, 0, 145))
        try:
            f = ImageFont.truetype("Arial.ttf", 44)
        except OSError:
            f = ImageFont.load_default()
        d.text((50, 55), title[:60], font=f, fill=(255, 255, 255, 255))
        return img

    def assemble(
        self,
        scene_clips: List[Path],
        scene_durations: List[float],
        voice_audio: Path,
        bg_music: Path,
        subtitles: List[SubtitleLine],
        title: str,
        out_path: Path,
    ) -> Path:
        if not scene_clips:
            raise ValueError("No scene clips provided for assembly.")
        clips = []
        transition = 0.16 if len(scene_clips) > 1 else 0.0
        for i, p in enumerate(scene_clips):
            base = self._fit_vertical(VideoFileClip(str(p)).without_audio())
            dur = scene_durations[i] if i < len(scene_durations) and scene_durations[i] > 0 else 6.0
            # Keep scene timing in sync while allowing a small overlap transition.
            target_dur = dur + (transition if i < len(scene_clips) - 1 else 0.0)
            if base.duration >= target_dur:
                part = base.subclip(0, target_dur)
            else:
                loops = [base]
                total = base.duration
                while total < target_dur:
                    loops.append(base.copy())
                    total += base.duration
                part = concatenate_videoclips(loops).subclip(0, target_dur)
            clips.append(part)

        if transition > 0:
            for i in range(1, len(clips)):
                clips[i] = clips[i].crossfadein(transition)
            video = concatenate_videoclips(clips, method="compose", padding=-transition)
        else:
            video = concatenate_videoclips(clips, method="compose")

        voice = AudioFileClip(str(voice_audio)).volumex(1.0)
        if voice.duration <= 0:
            raise ValueError("Voice audio is empty.")
        duration = voice.duration
        if video.duration > duration:
            video = video.subclip(0, duration)
        elif video.duration < duration:
            freeze = ImageClip(video.get_frame(max(0.0, video.duration - 0.03))).set_duration(duration - video.duration)
            freeze = freeze.set_position(("center", "center"))
            video = concatenate_videoclips([video, freeze], method="compose")

        music = AudioFileClip(str(bg_music)).volumex(0.16)
        if music.duration < duration:
            loops = int(duration // music.duration) + 1
            music = concatenate_audioclips([music] * loops)
        music = music.subclip(0, duration)
        audio = CompositeAudioClip([music, voice.subclip(0, duration)])

        layers = [video]
        for s in subtitles:
            img = self._subtitle_image(s.text)
            layers.append(ImageClip(np.array(img)).set_start(s.start).set_end(s.end).set_position(("center", self.size[1] - 340)))
        title_img = self._title_image(title)
        layers.append(ImageClip(np.array(title_img)).set_duration(duration).set_position(("center", 60)))

        final = CompositeVideoClip(layers).set_audio(audio)
        final.write_videofile(
            str(out_path),
            codec="libx264",
            audio_codec="aac",
            fps=self.fps,
            threads=4,
            bitrate="8M",
            ffmpeg_params=["-pix_fmt", "yuv420p"],
            verbose=False,
            logger=None,
        )

        final.close()
        video.close()
        voice.close()
        music.close()
        for c in clips:
            c.close()
        return out_path
