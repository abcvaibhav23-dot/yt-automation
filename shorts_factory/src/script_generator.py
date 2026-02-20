"""Generate daily short-form scripts by style/channel."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import choice
from typing import Optional

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
    "regional": [
        "Yahan ki mitti aur mehnat dono asli taqat hain.",
        "Chhote shehron se bade sapne nikalte hain roz.",
        "Apni boli, apni pehchan, apna confidence.",
    ],
}

HOOKS = {
    "tech": [
        "Aaj ka hack genuinely kaam ka hai.",
        "Ye setting on karke dekho, difference turant milega.",
    ],
    "funny": [
        "Sach bolo, ye scene aapke saath bhi hua hai.",
        "Is pe hasna mana nahi hai.",
    ],
    "bhakti": [
        "Bas 20 second ka pause lo aur suno.",
        "Aaj ki soch chhoti hai, impact bada hai.",
    ],
    "mirzapuri": [
        "Seedhi baat karte hain, bina filter ke.",
        "Suno dhyan se, baat dil tak jayegi.",
    ],
    "regional": [
        "Ek chhoti si baat, par kaam ki baat.",
        "Yeh line apne logon ke liye hai.",
    ],
}

OUTROS = {
    "tech": "Follow for more practical tech hacks every day!",
    "funny": "Like, share, and tag your funniest friend!",
    "bhakti": "Har din ek achchi soch ke saath shuru kariye. Jai ho.",
    "mirzapuri": "Aisan aur content chahi to follow thok da bhai!",
    "regional": "Aise hi regional shorts ke liye follow karo aur share karo!",
}

REGION_OPENINGS = {
    "mirzapur": "Mirzapur wale energy ke saath",
    "sonbhadra": "Sonbhadra ke swag aur dum ke saath",
    "bihar": "Bihar ke jazbe aur junoon ke saath",
}


def _normalize_style(style: str) -> str:
    normalized = style.strip().lower()
    if normalized == "motivation":
        return "bhakti"
    if normalized not in TOPICS:
        raise ValueError(f"Unsupported style '{style}'. Choose from: {', '.join(TOPICS)}")
    return normalized


def _normalize_region(region: Optional[str]) -> str:
    if not region:
        return "mirzapur"
    return region.strip().lower()


def _regional_topic(region: str) -> str:
    if region == "mirzapur":
        return choice(TOPICS["mirzapuri"])

    regional_lines = {
        "sonbhadra": [
            "Sonbhadra ki zameen jitni mazboot, utna hi strong yahan ka mindset.",
            "Local talent ko bas ek mauka chahiye, phir game badal jata hai.",
            "Gaon se city tak, mehnat ka level same high rehta hai.",
        ],
        "bihar": [
            "Bihar ka confidence simple hai: mehnat karo aur seedha result lao.",
            "Yahan se nikle ideas desh bhar mein impact banate hain.",
            "Discipline aur hustle ka combo, yehi Bihar style hai.",
        ],
    }
    return choice(regional_lines.get(region, TOPICS["regional"]))


def generate_script(
    style: str,
    channel_name: str,
    scripts_dir: Path,
    region: Optional[str] = None,
) -> ScriptResult:
    """Generate a script file for a given style and channel."""
    normalized_style = _normalize_style(style)
    normalized_region = _normalize_region(region)

    if normalized_style in {"mirzapuri", "regional"}:
        opening = (
            f"Namaste doston, {channel_name} mein swagat hai. "
            f"{REGION_OPENINGS.get(normalized_region, f'{normalized_region.title()} style ke saath')}."
        )
        topic = _regional_topic(normalized_region)
    else:
        opening = f"Namaste doston, {channel_name} mein swagat hai."
        topic = choice(TOPICS[normalized_style])
    hook = choice(HOOKS[normalized_style])
    mid = "Dhyan se suno."
    outro = OUTROS.get(normalized_style, OUTROS["regional"])

    script_text = f"{opening} {hook} {mid} {topic} {outro}"

    filename = f"{datetime.now().strftime('%Y-%m-%d')}_{normalized_style}_{timestamp_slug()}.txt"
    script_path = scripts_dir / filename
    script_path.write_text(script_text, encoding="utf-8")

    return ScriptResult(script_text=script_text, script_path=script_path)
