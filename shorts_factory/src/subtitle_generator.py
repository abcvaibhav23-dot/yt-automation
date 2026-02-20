"""Subtitle chunking logic from script text + audio duration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from mutagen.mp3 import MP3


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str


def get_audio_duration_seconds(audio_file: Path) -> float:
    audio = MP3(str(audio_file))
    if not audio.info or not audio.info.length:
        raise ValueError(f"Could not read duration for {audio_file}")
    return float(audio.info.length)


def generate_subtitles(script_text: str, audio_file: Path, words_per_chunk: int = 5) -> List[SubtitleEntry]:
    """Split script into subtitle entries and distribute over audio timeline."""
    words = script_text.strip().split()
    if not words:
        raise ValueError("Script text is empty. Cannot generate subtitles.")

    duration = get_audio_duration_seconds(audio_file)
    chunks = [words[i : i + words_per_chunk] for i in range(0, len(words), words_per_chunk)]

    chunk_duration = duration / len(chunks)
    entries: List[SubtitleEntry] = []
    for index, chunk in enumerate(chunks):
        start = index * chunk_duration
        end = min(duration, (index + 1) * chunk_duration)
        entries.append(SubtitleEntry(start=start, end=end, text=" ".join(chunk)))

    return entries


def save_srt(entries: List[SubtitleEntry], srt_path: Path) -> Path:
    """Save subtitle entries to SRT format."""

    def _format_ts(seconds: float) -> str:
        ms = int((seconds - int(seconds)) * 1000)
        total = int(seconds)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    lines = []
    for i, entry in enumerate(entries, start=1):
        lines.extend(
            [
                str(i),
                f"{_format_ts(entry.start)} --> {_format_ts(entry.end)}",
                entry.text,
                "",
            ]
        )

    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return srt_path
