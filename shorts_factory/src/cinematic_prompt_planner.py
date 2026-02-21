"""Scene prompt planning for richer, non-repetitive visual retrieval."""
from __future__ import annotations

import hashlib
import re
from typing import List, Optional, Sequence

from .subtitle_generator import SubtitleEntry


STYLE_MOODS = {
    "tech": ["futuristic", "clean", "neon", "smart city", "innovation"],
    "funny": ["playful", "colorful", "street candid", "expressive", "quirky"],
    "bhakti": ["spiritual", "serene", "golden hour", "temple", "meditative"],
    "mirzapuri": ["small town", "dusty street", "authentic", "dramatic", "local"],
    "regional": ["rural life", "community", "festival", "market", "documentary"],
}

CAMERA_STYLES = [
    "cinematic close-up",
    "wide establishing shot",
    "tracking shot",
    "drone aerial",
    "slow motion",
    "handheld documentary",
]

LIGHTING = [
    "golden hour lighting",
    "soft daylight",
    "high contrast",
    "moody cinematic light",
    "natural ambient light",
]


_STOP_WORDS = {
    "this",
    "that",
    "with",
    "from",
    "your",
    "have",
    "will",
    "into",
    "about",
    "here",
    "today",
    "quick",
    "short",
    "for",
    "and",
    "the",
    "you",
    "are",
    "hai",
    "hain",
    "ke",
    "ka",
}


def _keywords(text: str, max_terms: int = 6) -> List[str]:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return [w for w in words if len(w) > 3 and w not in _STOP_WORDS][:max_terms]


def _pick(items: Sequence[str], seed: int) -> str:
    if not items:
        return ""
    return items[seed % len(items)]


def plan_scene_prompts(
    subtitles: Sequence[SubtitleEntry],
    style: str,
    region: Optional[str] = None,
) -> List[str]:
    normalized = style.lower().strip()
    if normalized == "motivation":
        normalized = "bhakti"
    moods = STYLE_MOODS.get(normalized, STYLE_MOODS["regional"])

    region_hint = ""
    if region:
        region_hint = f"{region.strip()} india"

    prompts: List[str] = []
    for idx, entry in enumerate(subtitles):
        key_seed = int(hashlib.md5(f"{entry.text}-{idx}".encode("utf-8")).hexdigest()[:8], 16)
        words = _keywords(entry.text)
        subject = " ".join(words[:4]) if words else "people life story"
        mood = _pick(moods, key_seed)
        camera = _pick(CAMERA_STYLES, key_seed // 3)
        lighting = _pick(LIGHTING, key_seed // 7)

        bits = [subject, mood, camera, lighting]
        if region_hint:
            bits.append(region_hint)
        bits.append("vertical 9:16")
        bits.append("high detail")

        # remove empties and duplicates while preserving order
        seen = set()
        ordered = []
        for b in bits:
            b = b.strip()
            if not b or b in seen:
                continue
            seen.add(b)
            ordered.append(b)

        prompts.append(", ".join(ordered))

    return prompts
