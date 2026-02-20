"""Generate daily short-form scripts by style/channel."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import choice

from .config import timestamp_slug


@dataclass
class ScriptResult:
    script_text: str
    script_path: Path


TOPICS = {
    "tech": [
        "One hidden smartphone setting that boosts battery life.",
        "3 keyboard shortcuts that make you 2x faster.",
        "A tiny automation trick that saves 30 minutes daily.",
    ],
    "funny": [
        "When your alarm rings and you negotiate for five more minutes.",
        "That one friend who says 'I'm outside' but is still at home.",
        "Office Wi-Fi during meetings vs during lunch break.",
    ],
    "bhakti": [
        "Start your morning with gratitude and one deep breath.",
        "Discipline is devotion in action.",
        "Let your effort be your prayer and your patience be your strength.",
    ],
    "mirzapuri": [
        "Are bhai, je zindagi hae na, dheere-dheere samajh mein aavat hae.",
        "Mehnat karo, naam khud ban jaayi Mirzapur style mein.",
        "Gali ke joke aur asli dosti, ee dono priceless ba.",
    ],
}

OUTROS = {
    "tech": "Follow for more practical tech hacks every day!",
    "funny": "Like, share, and tag your funniest friend!",
    "bhakti": "Har din ek achchi soch ke saath shuru kariye. Jai ho.",
    "mirzapuri": "Aisan aur content chahi to follow thok da bhai!",
}


def _normalize_style(style: str) -> str:
    normalized = style.strip().lower()
    if normalized == "motivation":
        return "bhakti"
    if normalized not in TOPICS:
        raise ValueError(f"Unsupported style '{style}'. Choose from: {', '.join(TOPICS)}")
    return normalized


def generate_script(style: str, channel_name: str, scripts_dir: Path) -> ScriptResult:
    """Generate a script file for a given style and channel."""
    normalized_style = _normalize_style(style)

    opening = f"Welcome to {channel_name}!"
    topic = choice(TOPICS[normalized_style])
    mid = "Here is today's quick short."
    outro = OUTROS[normalized_style]

    script_text = f"{opening} {mid} {topic} {outro}"

    filename = f"{datetime.now().strftime('%Y-%m-%d')}_{normalized_style}_{timestamp_slug()}.txt"
    script_path = scripts_dir / filename
    script_path.write_text(script_text, encoding="utf-8")

    return ScriptResult(script_text=script_text, script_path=script_path)
