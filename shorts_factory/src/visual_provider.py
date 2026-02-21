"""External royalty-free visual providers with robust retries."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import List, Optional, Sequence

import requests
from .secrets_manager import get_secret


@dataclass(frozen=True)
class SceneAsset:
    kind: str  # "video" or "image"
    path: Path
    provider: str


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "shorts-factory/1.0"})
    return s


def _download_binary(url: str, out: Path, timeout: int = 30, attempts: int = 2) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(attempts):
        try:
            with requests.get(url, stream=True, timeout=timeout) as resp:
                if resp.status_code != 200:
                    continue
                with out.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            fh.write(chunk)
            if out.exists() and out.stat().st_size > 1024:
                return True
        except requests.RequestException:
            continue
    out.unlink(missing_ok=True)
    return False


def _pick_pexels_video_file(video_files: Sequence[dict]) -> Optional[str]:
    mp4s = [vf for vf in video_files if vf.get("file_type") == "video/mp4" and vf.get("link")]
    if not mp4s:
        return None
    mp4s.sort(key=lambda x: int(x.get("width") or 0) * int(x.get("height") or 0), reverse=True)
    return str(mp4s[0]["link"])


def _fetch_pexels_asset(
    session: requests.Session,
    query: str,
    index: int,
    cache_dir: Path,
    used_ids: set[int],
) -> Optional[SceneAsset]:
    api_key = get_secret("PEXELS_API_KEY")
    if not api_key:
        return None
    headers = {"Authorization": api_key}

    try:
        video_resp = session.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": query, "per_page": 15, "orientation": "portrait"},
            timeout=25,
        )
        if video_resp.status_code == 200:
            videos = video_resp.json().get("videos", [])
            videos.sort(key=lambda v: int(v.get("duration") or 0), reverse=True)
            for item in videos:
                media_id = int(item.get("id") or 0)
                if media_id in used_ids:
                    continue
                file_url = _pick_pexels_video_file(item.get("video_files", []))
                if not file_url:
                    continue
                key = hashlib.md5(f"pexels-video-{media_id}-{query}".encode("utf-8")).hexdigest()[:12]
                out = cache_dir / f"scene_{index:03}_{key}.mp4"
                if _download_binary(file_url, out):
                    used_ids.add(media_id)
                    return SceneAsset(kind="video", path=out, provider="pexels")
    except requests.RequestException:
        pass

    try:
        photo_resp = session.get(
            "https://api.pexels.com/v1/search",
            headers=headers,
            params={"query": query, "per_page": 15, "orientation": "portrait"},
            timeout=25,
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
                if _download_binary(str(file_url), out):
                    used_ids.add(media_id)
                    return SceneAsset(kind="image", path=out, provider="pexels")
    except requests.RequestException:
        pass
    return None


def _fetch_pixabay_asset(
    session: requests.Session,
    query: str,
    index: int,
    cache_dir: Path,
    used_ids: set[int],
) -> Optional[SceneAsset]:
    api_key = get_secret("PIXABAY_API_KEY")
    if not api_key:
        return None

    try:
        video_resp = session.get(
            "https://pixabay.com/api/videos/",
            params={"key": api_key, "q": query, "per_page": 15, "safesearch": "true"},
            timeout=25,
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
                if _download_binary(str(file_url), out):
                    used_ids.add(media_id)
                    return SceneAsset(kind="video", path=out, provider="pixabay")
    except requests.RequestException:
        pass

    try:
        photo_resp = session.get(
            "https://pixabay.com/api/",
            params={"key": api_key, "q": query, "per_page": 15, "safesearch": "true"},
            timeout=25,
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
                if _download_binary(str(file_url), out):
                    used_ids.add(media_id)
                    return SceneAsset(kind="image", path=out, provider="pixabay")
    except requests.RequestException:
        pass

    return None


def resolve_scene_assets(
    prompts: Sequence[str],
    cache_dir: Path,
) -> List[Optional[SceneAsset]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    used_ids: set[int] = set()
    resolved: List[Optional[SceneAsset]] = []
    session = _session()

    for idx, prompt in enumerate(prompts):
        asset = _fetch_pexels_asset(session=session, query=prompt, index=idx, cache_dir=cache_dir, used_ids=used_ids)
        if asset is None:
            asset = _fetch_pixabay_asset(session=session, query=prompt, index=idx, cache_dir=cache_dir, used_ids=used_ids)
        resolved.append(asset)

    return resolved
