"""Retention scoring logic."""
from __future__ import annotations

from typing import Dict, List

EMOTIONAL_WORDS = {"shock", "secret", "crazy", "instant", "truth", "fail", "mistake", "win", "power", "danger"}
CURIOSITY_WORDS = {"why", "how", "what", "revealed", "unexpected", "but", "wait"}
CTA_WORDS = {"follow", "share", "comment", "subscribe", "save", "try"}


def _word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])


def score_script(script: Dict) -> Dict:
    scenes: List[Dict] = script.get("scenes", [])
    if not scenes:
        return {"score": 0, "breakdown": {"error": "no scenes"}}

    first = scenes[0].get("text", "")
    all_text = " ".join(scene.get("text", "") for scene in scenes).lower()

    hook_score = 25 if _word_count(first) <= 14 else 12
    question_score = 10 if "?" in first or "?" in all_text else 0
    emotion_score = min(15, sum(1 for w in EMOTIONAL_WORDS if w in all_text) * 3)
    curiosity_score = min(15, sum(1 for w in CURIOSITY_WORDS if w in all_text) * 3)

    lengths = [_word_count(scene.get("text", "")) for scene in scenes]
    variation_score = 10 if len(set(lengths)) >= 3 else 5

    duration = float(script.get("total_duration", 0))
    duration_score = 15 if 30 <= duration <= 75 else 5

    cta_text = scenes[-1].get("text", "").lower()
    cta_score = 10 if any(w in cta_text for w in CTA_WORDS) else 4

    total = hook_score + question_score + emotion_score + curiosity_score + variation_score + duration_score + cta_score
    return {
        "score": int(min(100, total)),
        "breakdown": {
            "hook": hook_score,
            "question": question_score,
            "emotion": emotion_score,
            "curiosity": curiosity_score,
            "variation": variation_score,
            "duration": duration_score,
            "cta": cta_score,
        },
    }
