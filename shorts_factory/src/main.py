"""CLI entry point for generating YouTube shorts."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from random import choice
from typing import Optional

from .config import AppPaths, timestamp_slug
from .logger_setup import build_logger
from .script_generator import generate_script
from .subtitle_generator import generate_subtitles, save_srt
from .tts_engine import TTSError, VoiceConfig, script_to_audio
from .video_builder import build_short_video


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube Shorts Factory")
    parser.add_argument(
        "--channel",
        required=True,
        help="Channel name (example: Tech Daily)",
    )
    parser.add_argument(
        "--style",
        required=True,
        choices=["tech", "funny", "bhakti", "motivation", "mirzapuri", "regional"],
        help="Content style for script generation",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="mirzapur",
        help="Regional flavor for mirzapuri/regional styles (e.g. mirzapur, sonbhadra, bihar)",
    )
    parser.add_argument(
        "--script-file",
        type=str,
        default=None,
        help="Optional path to an existing script text file",
    )
    parser.add_argument(
        "--background",
        type=str,
        default=None,
        help="Optional background image/video path",
    )
    parser.add_argument(
        "--voice-lang",
        type=str,
        default="en",
        help="gTTS voice language code (en, hi, etc.)",
    )
    parser.add_argument(
        "--voice-tld",
        type=str,
        default="com",
        help="gTTS top-level domain for stable voice variant",
    )
    parser.add_argument(
        "--voice-name",
        type=str,
        default=None,
        help="Optional macOS voice name for natural narration (example: Aman, Samantha)",
    )
    parser.add_argument(
        "--no-srt",
        action="store_true",
        help="Do not export a sidecar .srt file (captions in video remain enabled)",
    )
    parser.add_argument(
        "--ai-visuals",
        action="store_true",
        help="Auto-fetch and sync scene visuals from royalty-free providers (Pexels/Pixabay) using subtitle text",
    )
    parser.add_argument(
        "--keep-history",
        action="store_true",
        help="Keep old generated files. By default, old generated scripts/audio/output/cache are removed before run.",
    )
    return parser.parse_args()


def load_or_generate_script(
    script_file: Optional[str],
    style: str,
    channel: str,
    scripts_dir: Path,
    region: str,
):
    if script_file:
        path = Path(script_file).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Script file not found: {path}")
        return path.read_text(encoding="utf-8").strip(), path

    generated = generate_script(
        style=style,
        channel_name=channel,
        scripts_dir=scripts_dir,
        region=region,
    )
    return generated.script_text, generated.script_path


def _cleanup_generated_files(paths: AppPaths, logger) -> None:
    date_style_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_.+_\d{8}_\d{6}\.txt$")
    removed = 0

    for p in paths.scripts.glob("*.txt"):
        if date_style_pattern.match(p.name):
            p.unlink(missing_ok=True)
            removed += 1

    for folder in [paths.audio, paths.output]:
        for p in folder.glob("*"):
            if p.is_file() and p.name != ".gitkeep":
                p.unlink(missing_ok=True)
                removed += 1

    for cache_name in ["scene_cache"]:
        cache_dir = paths.assets / cache_name
        if cache_dir.exists():
            for p in cache_dir.glob("*"):
                if p.is_file():
                    p.unlink(missing_ok=True)
                    removed += 1

    logger.info("Fresh run cleanup completed. Removed %d generated files.", removed)


def run() -> int:
    args = parse_args()
    paths = AppPaths.discover()
    paths.ensure_directories()

    logger = build_logger(paths.logs / "shorts_factory.log")
    logger.info("Starting run for channel='%s', style='%s'", args.channel, args.style)

    try:
        if not args.keep_history:
            _cleanup_generated_files(paths, logger)

        script_text, script_path = load_or_generate_script(
            script_file=args.script_file,
            style=args.style,
            channel=args.channel,
            scripts_dir=paths.scripts,
            region=args.region,
        )
        logger.info("Using script file: %s", script_path)

        stamp = timestamp_slug()
        audio_path = paths.audio / f"{args.style}_{stamp}.mp3"
        srt_path = paths.output / f"{args.style}_{stamp}.srt"
        video_path = paths.output / f"{args.style}_{stamp}.mp4"

        voice = VoiceConfig(
            language=args.voice_lang,
            tld=args.voice_tld,
            slow=False,
            voice_name=args.voice_name,
        )
        script_to_audio(script_text=script_text, output_audio=audio_path, voice=voice)
        logger.info("Audio generated: %s", audio_path)

        subtitles = generate_subtitles(script_text=script_text, audio_file=audio_path)
        if not args.no_srt:
            save_srt(subtitles, srt_path)
            logger.info("Subtitles generated: %s", srt_path)
        else:
            logger.info("Skipping sidecar SRT export (--no-srt enabled)")

        if args.background:
            background = Path(args.background).expanduser().resolve()
        else:
            candidates = []
            for ext in ("*.mp4", "*.mov", "*.mkv", "*.webm", "*.jpg", "*.jpeg", "*.png", "*.webp"):
                candidates.extend(paths.assets.glob(ext))
            background = choice(candidates).resolve() if candidates else None
        if background and not background.exists():
            raise FileNotFoundError(f"Background file not found: {background}")

        build_short_video(
            audio_path=audio_path,
            subtitles=subtitles,
            output_path=video_path,
            background_path=background,
            ai_visuals=args.ai_visuals,
            assets_dir=paths.assets,
        )
        logger.info("Video exported: %s", video_path)

        print(f"Success! Video created at: {video_path}")
        return 0
    except (ValueError, FileNotFoundError, TTSError) as exc:
        logger.error("Known error: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error")
        print(f"Unexpected failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
