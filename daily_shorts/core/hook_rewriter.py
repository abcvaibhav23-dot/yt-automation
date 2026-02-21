"""Rewrite only hook when score is low."""
from __future__ import annotations

import json
import re
from typing import Dict, List, Tuple

import requests

from config.settings import DATA_DIR
from config.settings import OPENAI_API_KEY, OPENAI_MODEL
from core.retention_scorer import score_script


def _norm_sig(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))


def _recent_hook_sigs(limit: int = 30) -> set[str]:
    path = DATA_DIR / "history.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        runs = list(payload.get("runs", []))[-limit:]
        return {_norm_sig(r.get("hook_variant", "")) for r in runs if r.get("hook_variant")}
    except Exception:
        return set()


def _local_hook_variants(topic: str) -> List[str]:
    return [
        f"Wait... {topic} mein aapki #1 hidden mistake kya hai?",
        f"Ruko... {topic} ka secret truth kya hai, pata hai?",
        f"What if {topic} ka power step aap miss kar rahe ho?",
        f"Agar aap {topic} karte ho, ye 1 danger point skip mat karna!",
        f"Unexpected truth: {topic} ka win formula log ulta karte hain.",
        f"{topic} mein result rukta kyun hai jab effort same hai?",
        f"Ek sawaal: {topic} mein aap pehla step galat toh nahi le rahe?",
    ]


def _openai_hook_variants(topic: str, language_mode: str) -> List[str]:
    if not OPENAI_API_KEY:
        return _local_hook_variants(topic)
    prompt = (
        f"Generate 3 short hook lines for topic '{topic}'. Language mode {language_mode}. "
        "Must be spoken-friendly and curiosity-heavy. Return JSON: {\"hooks\":[\"...\",\"...\",\"...\"]}"
    )
    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.9,
        "max_tokens": 120,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You write viral YouTube Shorts hooks."},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=40)
        if r.status_code != 200:
            return _local_hook_variants(topic)
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        hooks = [str(x).strip() for x in data.get("hooks", []) if str(x).strip()]
        return hooks[:3] if hooks else _local_hook_variants(topic)
    except Exception:
        return _local_hook_variants(topic)


def rewrite_best_hook(script: Dict, topic: str, language_mode: str) -> Tuple[Dict, str, int]:
    hooks = _openai_hook_variants(topic, language_mode)
    blocked = _recent_hook_sigs()
    hooks = [h for h in hooks if _norm_sig(h) not in blocked] or _local_hook_variants(topic)
    best_script = script
    best_variant = script["scenes"][0]["text"]
    best_score = score_script(script)["score"]

    for hook in hooks:
        candidate = json.loads(json.dumps(script))
        candidate["scenes"][0]["text"] = hook
        score = score_script(candidate)["score"]
        if score > best_score:
            best_script, best_variant, best_score = candidate, hook, score

    api_calls = 1 if OPENAI_API_KEY else 0
    return best_script, best_variant, api_calls
