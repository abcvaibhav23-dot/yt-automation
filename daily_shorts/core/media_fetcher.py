"""Fetch stock clips from Pixabay then Pexels with caching and cooldown."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from config.settings import FFMPEG_BINARY, MIN_CLIP_HEIGHT, MIN_CLIP_WIDTH, PEXELS_API_KEY, PIXABAY_API_KEY


@dataclass
class ClipInfo:
    path: Path
    keyword: str
    provider: str


class MediaFetcher:
    def __init__(self, cache_dir: Path, keywords_db_path: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.keywords_db_path = keywords_db_path
        self.api_calls = {"pixabay": 0, "pexels": 0}
        self.provider_disabled = {"pixabay": False, "pexels": False}
        self.db = self._load_db()

    def _load_db(self) -> Dict:
        if not self.keywords_db_path.exists():
            return {"keywords": {}, "clip_usage": {}}
        try:
            payload = json.loads(self.keywords_db_path.read_text(encoding="utf-8"))
            payload.setdefault("keywords", {})
            payload.setdefault("clip_usage", {})
            return payload
        except json.JSONDecodeError:
            return {"keywords": {}, "clip_usage": {}}

    def _save_db(self) -> None:
        self.keywords_db_path.write_text(json.dumps(self.db, ensure_ascii=False, indent=2), encoding="utf-8")

    def _clip_in_cooldown(self, clip_path: Path, days: int = 3) -> bool:
        key = clip_path.name
        raw = self.db.get("clip_usage", {}).get(key)
        if not raw:
            return False
        try:
            used_at = datetime.fromisoformat(raw)
        except ValueError:
            return False
        return datetime.utcnow() - used_at < timedelta(days=days)

    def _mark_clip_used(self, clip_path: Path) -> None:
        self.db.setdefault("clip_usage", {})[clip_path.name] = datetime.utcnow().isoformat()
        self._save_db()

    def _hash_name(self, text: str, suffix: str) -> Path:
        key = hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{key}.{suffix}"

    @staticmethod
    def _build_scene_queries(scene: Dict, allowed_keywords: List[str]) -> List[str]:
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "have", "your", "just", "about",
            "scene", "real", "short", "india", "hota", "hogi", "hai", "mein", "ke", "ki", "ka",
        }
        keywords = [str(k).strip().lower() for k in scene.get("keywords", []) if str(k).strip()]
        if allowed_keywords:
            keywords = [k for k in keywords if k in {x.lower() for x in allowed_keywords}] or keywords
        text = str(scene.get("text", "")).lower()
        tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", text) if t not in stop]
        queries: List[str] = []
        queries.extend(keywords[:3])
        for t in tokens[:4]:
            if t not in queries:
                queries.append(t)
        if keywords and tokens:
            combo = f"{keywords[0]} {tokens[0]}"
            if combo not in queries:
                queries.append(combo)
        if not queries:
            queries = ["india lifestyle"]
        return queries[:2]

    def _generate_fallback_clip(self, keyword: str, index: int) -> Path:
        out = self._hash_name(f"fallback-{keyword}-{index}", "mp4")
        if out.exists() and out.stat().st_size > 50_000:
            return out
        # Dynamic local pattern clip to avoid blank output when stock APIs are unavailable.
        source = "testsrc2=size=1080x1920:rate=30"
        hue_shift = (index * 38) % 360
        sat = 0.52 + (index % 4) * 0.08
        bright = -0.03 + (index % 3) * 0.02
        vf = (
            f"hue=h={hue_shift}:s={sat:.2f},"
            f"eq=contrast=1.08:brightness={bright:.2f},"
            f"drawbox=x='mod(t*220+{index * 37},w)':y='h*0.72':w=220:h=90:color=black@0.30:t=fill"
        )
        cmd = [
            FFMPEG_BINARY,
            "-y",
            "-f",
            "lavfi",
            "-i",
            source,
            "-t",
            "8",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out

    def _download(self, url: str, out: Path) -> bool:
        try:
            with requests.get(url, stream=True, timeout=40) as r:
                if r.status_code != 200:
                    return False
                with out.open("wb") as f:
                    for chunk in r.iter_content(1024 * 128):
                        if chunk:
                            f.write(chunk)
            return out.exists() and out.stat().st_size > 200_000
        except requests.RequestException:
            return False

    def _pixabay(self, keyword: str) -> List[Tuple[str, str]]:
        if not PIXABAY_API_KEY or self.provider_disabled["pixabay"]:
            return []
        self.api_calls["pixabay"] += 1
        try:
            r = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": PIXABAY_API_KEY, "q": keyword, "per_page": 10, "safesearch": "true"},
                timeout=30,
            )
            if r.status_code != 200:
                return []
            hits = r.json().get("hits", [])
            found: List[Tuple[str, str]] = []
            for h in hits:
                variants = h.get("videos", {})
                for key in ["large", "medium", "small", "tiny"]:
                    meta = variants.get(key, {})
                    url = meta.get("url")
                    w = int(meta.get("width") or 0)
                    hgt = int(meta.get("height") or 0)
                    if url and w >= MIN_CLIP_WIDTH and hgt >= MIN_CLIP_HEIGHT and hgt > w:
                        found.append((url, "mp4"))
                        break
            return found
        except requests.RequestException:
            self.provider_disabled["pixabay"] = True
            return []

    def _pexels(self, keyword: str) -> List[Tuple[str, str]]:
        if not PEXELS_API_KEY or self.provider_disabled["pexels"]:
            return []
        self.api_calls["pexels"] += 1
        try:
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": keyword, "per_page": 10, "orientation": "portrait"},
                timeout=30,
            )
            if r.status_code != 200:
                return []
            videos = r.json().get("videos", [])
            found: List[Tuple[str, str]] = []
            for v in videos:
                for f in v.get("video_files", []):
                    w = int(f.get("width") or 0)
                    hgt = int(f.get("height") or 0)
                    if f.get("file_type") == "video/mp4" and w >= MIN_CLIP_WIDTH and hgt >= MIN_CLIP_HEIGHT and hgt > w:
                        found.append((str(f.get("link")), "mp4"))
            return found
        except requests.RequestException:
            self.provider_disabled["pexels"] = True
            return []

    def fetch_scene_clips(self, scenes: List[Dict], allowed_keywords: List[str]) -> List[ClipInfo]:
        clips: List[ClipInfo] = []
        used_assets: set[str] = set()
        for i, scene in enumerate(scenes):
            queries = self._build_scene_queries(scene, allowed_keywords=allowed_keywords)
            selected = None
            selected_url: Optional[str] = None
            selected_query = queries[0]
            for query in queries:
                provider_candidates = [("pixabay", self._pixabay(query))]
                if not provider_candidates[0][1]:
                    provider_candidates.append(("pexels", self._pexels(query)))
                for provider, candidates in provider_candidates:
                    for url, _ in candidates:
                        cache_name = self._hash_name(url, "mp4")
                        if url in used_assets or cache_name.name in used_assets:
                            continue
                        if cache_name.exists() and cache_name.stat().st_size > 200_000:
                            if self._clip_in_cooldown(cache_name):
                                continue
                            selected = ClipInfo(cache_name, query, "cache")
                            selected_url = url
                            selected_query = query
                            break
                        if self._download(url, cache_name):
                            selected = ClipInfo(cache_name, query, provider)
                            selected_url = url
                            selected_query = query
                            break
                    if selected:
                        break
                if selected:
                    break

            if selected:
                clips.append(selected)
                used_assets.add(selected.path.name)
                if selected_url:
                    used_assets.add(selected_url)
                self._mark_clip_used(selected.path)
                continue

            # Hard fallback: generate a unique local clip per scene to avoid repeating the same visual.
            fallback = self._generate_fallback_clip(selected_query, i)
            clips.append(ClipInfo(fallback, selected_query, "fallback"))
            self._mark_clip_used(fallback)

        return clips
