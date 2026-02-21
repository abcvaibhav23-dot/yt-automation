"""Generate SEO metadata for final upload."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Dict, List


def build_metadata(channel: str, title: str, topic: str, keywords: List[str]) -> Dict:
    base_tags = [channel, "shorts", "ytshorts", "viral", "india", topic]
    merged = [k for k in keywords if k] + base_tags
    dedup = []
    seen = set()
    for k in merged:
        key = k.lower().strip()
        if key and key not in seen:
            seen.add(key)
            dedup.append(k)

    seo_title = f"{title} | {channel.title()} #shorts"
    openers = [
        f"Aaj ka topic: {topic}.",
        f"Quick short on {topic}.",
        f"{topic} par short insight.",
    ]
    ctas = [
        "Apna take comment mein likho.",
        "Agar useful laga ho toh share karo.",
        "Next kis topic pe short chahiye, comment karo.",
    ]
    description = (
        f"{random.choice(openers)}\n"
        f"Channel: {channel}\n"
        f"{random.choice(ctas)}\n"
        f"\n#shorts #ytshorts #{channel}"
    )
    topic_tag = re.sub(r"[^a-zA-Z0-9]", "", topic)[:24] or channel
    hashtags = [f"#{channel}", "#shorts", "#ytshorts", "#viral", f"#{topic_tag}", "#india"]
    pinned = random.choice(
        [
            f"{topic} mein aapka real experience kya hai?",
            "Aapke hisaab se sabse strong line kaunsi thi?",
            "Is short ka part-2 chahiye toh batao.",
        ]
    ) + " 👇"

    return {
        "seo_title": seo_title,
        "description": description,
        "hashtags": hashtags,
        "keywords": dedup[:25],
        "pinned_comment": pinned,
    }


def save_metadata(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
