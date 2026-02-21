"""Global settings for yt_automation."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # noqa: BLE001
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

OUTPUT_DIR = ROOT / "output"
FINAL_DIR = ROOT / "final"
LOG_DIR = ROOT / "logs"
CACHE_DIR = ROOT / "assets" / "cache"
MUSIC_DIR = ROOT / "assets" / "music"
DATA_DIR = ROOT / "data"
PROMPTS_DIR = ROOT / "prompts"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()

MIN_CLIP_WIDTH = int(os.getenv("MIN_CLIP_WIDTH", "720"))
MIN_CLIP_HEIGHT = int(os.getenv("MIN_CLIP_HEIGHT", "1280"))
MAX_WORDS = int(os.getenv("MAX_WORDS", "150"))
KEEP_FINAL_RUNS_PER_CHANNEL = int(os.getenv("KEEP_FINAL_RUNS_PER_CHANNEL", "1"))
KEEP_LOG_FILES = int(os.getenv("KEEP_LOG_FILES", "20"))
CACHE_MAX_AGE_DAYS = int(os.getenv("CACHE_MAX_AGE_DAYS", "7"))
CLEAN_CACHE_BY_RUN = os.getenv("CLEAN_CACHE_BY_RUN", "1").strip().lower() in {"1", "true", "yes"}

FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "ffmpeg")
FFPROBE_BINARY = os.getenv("FFPROBE_BINARY", "ffprobe")

for p in [OUTPUT_DIR, FINAL_DIR, LOG_DIR, CACHE_DIR, MUSIC_DIR, DATA_DIR]:
    p.mkdir(parents=True, exist_ok=True)
