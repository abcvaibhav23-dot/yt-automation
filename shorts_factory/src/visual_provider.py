"""External royalty-free visual providers with local fallback."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import List, Optional, Sequence

import requests

from .subtitle_generator import SubtitleEntry


@dataclass(frozen=True)
class SceneAsset:
    kind: str  # "video" or "image"
    path: Path
    provider: str
    source_url: str
    license_note: str
    attribution: str
    query: str


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


def _keywords_from_text(text: str) -> str:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    filtered = [w for w in words if len(w) > 3 and w not in _STOP_WORDS]
    if not filtered:
        filtered = ["cinematic", "city", "people"]
    return " ".join(filtered[:4])


def _download_binary(url: str, out: Path, timeout: int = 30) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            if resp.status_code != 200:
                return False
            with out.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        fh.write(chunk)
    except requests.RequestException:
        return False
    return out.exists() and out.stat().st_size > 1024


def _pick_pexels_video_file(video_files: Sequence[dict]) -> Optional[str]:
    mp4s = [vf for vf in video_files if vf.get("file_type") == "video/mp4" and vf.get("link")]
    if not mp4s:
        return None
    mp4s.sort(key=lambda x: int(x.get("width") or 0) * int(x.get("height") or 0), reverse=True)
    return str(mp4s[0]["link"])


def _fetch_pexels_asset(
    query: str,
    index: int,
    cache_dir: Path,
    used_ids: set[int],
) -> Optional[SceneAsset]:
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        return None
    headers = {"Authorization": api_key}

    # Prefer videos for richer motion scenes.
    try:
        video_resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": query, "per_page": 12, "orientation": "portrait"},
            timeout=20,
        )
        if video_resp.status_code == 200:
            videos = video_resp.json().get("videos", [])
            for item in videos:
                media_id = int(item.get("id") or 0)
                if media_id in used_ids:
                    continue
                file_url = _pick_pexels_video_file(item.get("video_files", []))
                if not file_url:
                    continue
                key = hashlib.md5(f"pexels-video-{media_id}-{query}".encode("utf-8")).hexdigest()[:12]
                out = cache_dir / f"scene_{index:03}_{key}.mp4"
                if out.exists() and out.stat().st_size > 1024:
                    used_ids.add(media_id)
                    return SceneAsset(
                        kind="video",
                        path=out,
                        provider="pexels",
                        source_url=f"https://www.pexels.com/video/{media_id}/",
                        license_note="Pexels license (royalty-free; check current terms).",
                        attribution="Pexels contributor",
                        query=query,
                    )
                if _download_binary(file_url, out):
                    used_ids.add(media_id)
                    return SceneAsset(
                        kind="video",
                        path=out,
                        provider="pexels",
                        source_url=f"https://www.pexels.com/video/{media_id}/",
                        license_note="Pexels license (royalty-free; check current terms).",
                        attribution="Pexels contributor",
                        query=query,
                    )
    except requests.RequestException:
        pass

    # Fallback to high-res photo if no suitable video.
    try:
        photo_resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers,
            params={"query": query, "per_page": 12, "orientation": "portrait"},
            timeout=20,
        )
        if photo_resp.status_code == 200:
            photos = photo_resp.json().get("photos", [])
            for item in photos:
                media_id = int(item.get("id") or 0)
                if media_id in used_ids:
                    continue
                src = item.get("src", {})
                file_url = src.get("large2x") or src.get("large") or src.get("original")
                if not file_url:
                    continue
                key = hashlib.md5(f"pexels-photo-{media_id}-{query}".encode("utf-8")).hexdigest()[:12]
                out = cache_dir / f"scene_{index:03}_{key}.jpg"
                if out.exists() and out.stat().st_size > 1024:
                    used_ids.add(media_id)
                    return SceneAsset(
                        kind="image",
                        path=out,
                        provider="pexels",
                        source_url=item.get("url", "https://www.pexels.com/"),
                        license_note="Pexels license (royalty-free; check current terms).",
                        attribution=item.get("photographer", "Pexels contributor"),
                        query=query,
                    )
                if _download_binary(str(file_url), out):
                    used_ids.add(media_id)
                    return SceneAsset(
                        kind="image",
                        path=out,
                        provider="pexels",
                        source_url=item.get("url", "https://www.pexels.com/"),
                        license_note="Pexels license (royalty-free; check current terms).",
                        attribution=item.get("photographer", "Pexels contributor"),
                        query=query,
                    )
    except requests.RequestException:
        pass
    return None


def _fetch_pixabay_asset(
    query: str,
    index: int,
    cache_dir: Path,
    used_ids: set[int],
) -> Optional[SceneAsset]:
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        video_resp = requests.get(
            "https://pixabay.com/api/videos/",
            params={
                "key": api_key,
                "q": query,
                "per_page": 12,
                "safesearch": "true",
            },
            timeout=20,
        )
        if video_resp.status_code == 200:
            videos = video_resp.json().get("hits", [])
            for item in videos:
                media_id = int(item.get("id") or 0)
                if media_id in used_ids:
                    continue
                variants = item.get("videos", {})
                file_url = (
                    variants.get("large", {}).get("url")
                    or variants.get("medium", {}).get("url")
                    or variants.get("small", {}).get("url")
                    or variants.get("tiny", {}).get("url")
                )
                if not file_url:
                    continue
                key = hashlib.md5(f"pixabay-video-{media_id}-{query}".encode("utf-8")).hexdigest()[:12]
                out = cache_dir / f"scene_{index:03}_{key}.mp4"
                if out.exists() and out.stat().st_size > 1024:
                    used_ids.add(media_id)
                    return SceneAsset(
                        kind="video",
                        path=out,
                        provider="pixabay",
                        source_url=item.get("pageURL", "https://pixabay.com/videos/"),
                        license_note="Pixabay license (royalty-free; check current terms).",
                        attribution=f"Pixabay user {item.get('user', 'unknown')}",
                        query=query,
                    )
                if _download_binary(str(file_url), out):
                    used_ids.add(media_id)
                    return SceneAsset(
                        kind="video",
                        path=out,
                        provider="pixabay",
                        source_url=item.get("pageURL", "https://pixabay.com/videos/"),
                        license_note="Pixabay license (royalty-free; check current terms).",
                        attribution=f"Pixabay user {item.get('user', 'unknown')}",
                        query=query,
                    )
    except requests.RequestException:
        pass

    try:
        photo_resp = requests.get(
            "https://pixabay.com/api/",
            params={"key": api_key, "q": query, "per_page": 12, "safesearch": "true"},
            timeout=20,
        )
        if photo_resp.status_code == 200:
            photos = photo_resp.json().get("hits", [])
            for item in photos:
                media_id = int(item.get("id") or 0)
                if media_id in used_ids:
                    continue
                file_url = item.get("largeImageURL") or item.get("webformatURL")
                if not file_url:
                    continue
                key = hashlib.md5(f"pixabay-photo-{media_id}-{query}".encode("utf-8")).hexdigest()[:12]
                out = cache_dir / f"scene_{index:03}_{key}.jpg"
                if out.exists() and out.stat().st_size > 1024:
                    used_ids.add(media_id)
                    return SceneAsset(
                        kind="image",
                        path=out,
                        provider="pixabay",
                        source_url=item.get("pageURL", "https://pixabay.com/images/"),
                        license_note="Pixabay license (royalty-free; check current terms).",
                        attribution=f"Pixabay user {item.get('user', 'unknown')}",
                        query=query,
                    )
                if _download_binary(str(file_url), out):
                    used_ids.add(media_id)
                    return SceneAsset(
                        kind="image",
                        path=out,
                        provider="pixabay",
                        source_url=item.get("pageURL", "https://pixabay.com/images/"),
                        license_note="Pixabay license (royalty-free; check current terms).",
                        attribution=f"Pixabay user {item.get('user', 'unknown')}",
                        query=query,
                    )
    except requests.RequestException:
        pass
    return None


def resolve_scene_assets(
    subtitles: Sequence[SubtitleEntry],
    assets_dir: Path,
) -> List[Optional[SceneAsset]]:
    cache_dir = assets_dir / "scene_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    used_ids: set[int] = set()

    resolved: List[Optional[SceneAsset]] = []
    for idx, sub in enumerate(subtitles):
        query = _keywords_from_text(sub.text)
        asset = _fetch_pexels_asset(query=query, index=idx, cache_dir=cache_dir, used_ids=used_ids)
        if asset is None:
            asset = _fetch_pixabay_asset(query=query, index=idx, cache_dir=cache_dir, used_ids=used_ids)
        resolved.append(asset)
    return resolved


def write_usage_report(scene_assets: Sequence[SceneAsset], output_path: Path) -> Path:
    lines = [
        "Scene media usage report",
        "Note: Royalty-free libraries reduce risk but do not guarantee zero claims. Review current license terms.",
        "",
    ]
    for idx, asset in enumerate(scene_assets, start=1):
        lines.append(
            f"{idx}. provider={asset.provider} kind={asset.kind} query='{asset.query}'"
        )
        lines.append(f"   source={asset.source_url}")
        lines.append(f"   attribution={asset.attribution}")
        lines.append(f"   license={asset.license_note}")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
