"""CLI entry point for generating YouTube shorts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
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
        choices=["tech", "funny", "bhakti", "motivation", "mirzapuri"],
        help="Content style for script generation",
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
    return parser.parse_args()


def load_or_generate_script(
    script_file: Optional[str],
    style: str,
    channel: str,
    scripts_dir: Path,
):
    if script_file:
        path = Path(script_file).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Script file not found: {path}")
        return path.read_text(encoding="utf-8").strip(), path

    generated = generate_script(style=style, channel_name=channel, scripts_dir=scripts_dir)
    return generated.script_text, generated.script_path


def run() -> int:
    args = parse_args()
    paths = AppPaths.discover()
    paths.ensure_directories()

    logger = build_logger(paths.logs / "shorts_factory.log")
    logger.info("Starting run for channel='%s', style='%s'", args.channel, args.style)

    try:
        script_text, script_path = load_or_generate_script(
            script_file=args.script_file,
            style=args.style,
            channel=args.channel,
            scripts_dir=paths.scripts,
        )
        logger.info("Using script file: %s", script_path)

        stamp = timestamp_slug()
        audio_path = paths.audio / f"{args.style}_{stamp}.mp3"
        srt_path = paths.output / f"{args.style}_{stamp}.srt"
        video_path = paths.output / f"{args.style}_{stamp}.mp4"

        voice = VoiceConfig(language=args.voice_lang, tld=args.voice_tld, slow=False)
        script_to_audio(script_text=script_text, output_audio=audio_path, voice=voice)
        logger.info("Audio generated: %s", audio_path)

        subtitles = generate_subtitles(script_text=script_text, audio_file=audio_path)
        save_srt(subtitles, srt_path)
        logger.info("Subtitles generated: %s", srt_path)

        background = Path(args.background).expanduser().resolve() if args.background else None
        if background and not background.exists():
            raise FileNotFoundError(f"Background file not found: {background}")

        build_short_video(
            audio_path=audio_path,
            subtitles=subtitles,
            output_path=video_path,
            background_path=background,
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
