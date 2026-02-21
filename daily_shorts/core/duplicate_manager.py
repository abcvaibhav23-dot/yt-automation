"""Track topics and keywords to avoid duplicates."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List


class DuplicateManager:
    def __init__(self, history_path: Path, keywords_path: Path, cooldown_days: int = 3) -> None:
        self.history_path = history_path
        self.keywords_path = keywords_path
        self.cooldown_days = cooldown_days
        self.history = self._load_json(history_path, {"used_topics": [], "runs": []})
        self.keywords = self._load_json(keywords_path, {"keywords": {}})

    @staticmethod
    def _load_json(path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def _save(self) -> None:
        self.history_path.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")
        self.keywords_path.write_text(json.dumps(self.keywords, ensure_ascii=False, indent=2), encoding="utf-8")

    def topic_used(self, topic: str) -> bool:
        return topic.lower().strip() in {t.lower().strip() for t in self.history.get("used_topics", [])}

    def keyword_allowed(self, keyword: str) -> bool:
        k = keyword.lower().strip()
        raw = self.keywords.get("keywords", {}).get(k)
        if not raw:
            return True
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            return True
        return datetime.utcnow() - last >= timedelta(days=self.cooldown_days)

    def filter_keywords(self, keywords: List[str]) -> List[str]:
        return [k for k in keywords if self.keyword_allowed(k)]

    def record_run(
        self,
        topic: str,
        channel: str,
        score: int,
        hook_variant: str,
        duration: float,
        api_calls: Dict[str, int],
        scene_texts: List[str] | None = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        topic_norm = topic.strip()
        if topic_norm and topic_norm not in self.history["used_topics"]:
            self.history["used_topics"].append(topic_norm)
        self.history["runs"].append(
            {
                "ts": now,
                "topic": topic_norm,
                "channel": channel,
                "score": score,
                "hook_variant": hook_variant,
                "scene_texts": scene_texts or [],
                "duration": duration,
                "api_calls": api_calls,
            }
        )
        self._save()

    def record_keywords(self, keywords: List[str]) -> None:
        now = datetime.utcnow().isoformat()
        store = self.keywords.setdefault("keywords", {})
        for k in keywords:
            store[k.lower().strip()] = now
        self._save()
