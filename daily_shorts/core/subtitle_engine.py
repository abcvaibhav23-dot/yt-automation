"""Subtitle creation and rendering helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class SubtitleLine:
    start: float
    end: float
    text: str


def _fmt(ts: float) -> str:
    ms = int(round(ts * 1000))
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_subtitles(scenes: List[Dict], scene_durations: List[float]) -> List[SubtitleLine]:
    lines: List[SubtitleLine] = []
    cursor = 0.0
    for i, scene in enumerate(scenes):
        dur = scene_durations[i] if i < len(scene_durations) and scene_durations[i] > 0 else float(scene.get("duration_estimate", 7))
        text = " ".join(str(scene.get("text", "")).split())
        lines.append(SubtitleLine(start=cursor, end=cursor + dur, text=text))
        cursor += dur
    return lines


def save_srt(lines: List[SubtitleLine], path: Path) -> None:
    chunks = []
    for i, line in enumerate(lines, start=1):
        chunks.append(f"{i}\n{_fmt(line.start)} --> {_fmt(line.end)}\n{line.text}\n")
    path.write_text("\n".join(chunks), encoding="utf-8")
