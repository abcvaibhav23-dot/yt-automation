"""CLI entry point for generating YouTube shorts."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from random import choice
from typing import Optional

from .config import AppPaths, timestamp_slug
from .logger_setup import build_logger
from .secrets_manager import get_secret, load_env_and_bind
from .script_generator import auto_content_prompt, generate_script
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
        "--content-prompt",
        type=str,
        default=None,
        help="Optional content hint to shape script generation.",
    )
    parser.add_argument(
        "--review-script",
        action="store_true",
        help="Show script and ask for approval before calling TTS/media providers.",
    )
    parser.add_argument(
        "--interactive-review",
        action="store_true",
        help="Interactive loop to tune prompt/script/pronunciation and preview voice before final generation.",
    )
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="Generate and show script only, then exit without using TTS/API credits.",
    )
    parser.add_argument(
        "--background",
        type=str,
        default=None,
        help="Optional background image/video path",
    )
    parser.add_argument(
        "--video-title",
        type=str,
        default=None,
        help="Optional title text overlay shown at the top of the video.",
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
        "--with-srt",
        action="store_true",
        help="Export sidecar .srt file (disabled by default to keep only audio/video outputs).",
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
    parser.add_argument(
        "--audio-mode",
        choices=["voice", "music", "both"],
        default="both",
        help="Audio mix mode: voice only, music only, or both.",
    )
    parser.add_argument(
        "--bg-music",
        type=str,
        default=None,
        help="Optional background music file path (.mp3/.wav/.m4a/.aac).",
    )
    parser.add_argument(
        "--voice-volume",
        type=float,
        default=1.0,
        help="Voice volume multiplier for final mix (default 1.0).",
    )
    parser.add_argument(
        "--bgm-volume",
        type=float,
        default=0.20,
        help="Background music volume multiplier for final mix (default 0.20).",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=220,
        help="Character count for voice preview snippet in interactive review mode.",
    )
    parser.add_argument(
        "--quality-mode",
        choices=["pro", "balanced", "fallback"],
        default="pro",
        help="Output quality policy: pro blocks low-quality fallback, balanced allows limited fallback, fallback always allows.",
    )
    return parser.parse_args()


def load_or_generate_script(
    script_file: Optional[str],
    style: str,
    channel: str,
    scripts_dir: Path,
    region: str,
    prompt_hint: Optional[str],
):
    if script_file:
        path = Path(script_file).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Script file not found: {path}")
        auto_prompt = auto_content_prompt(
            style=style,
            region=region,
            channel_name=channel,
            prompt_hint=prompt_hint,
        )
        return path.read_text(encoding="utf-8").strip(), path, auto_prompt

    generated = generate_script(
        style=style,
        channel_name=channel,
        scripts_dir=scripts_dir,
        region=region,
        persist=False,
        prompt_hint=prompt_hint,
    )
    return generated.script_text, generated.script_path, generated.content_prompt


def _confirm_script(script_text: str, content_prompt: str) -> str:
    print("\n--- Content Prompt ---")
    print(content_prompt)
    print("----------------------")
    print("\n--- Script Preview ---")
    print(script_text)
    print("----------------------\n")
    try:
        answer = input("Approve this script? [y=Yes / e=Edit / n=No]: ").strip().lower()
    except EOFError:
        return "n"
    if answer in {"y", "yes"}:
        return "y"
    if answer in {"e", "edit"}:
        return "e"
    return "n"


def _review_script_with_updates(
    *,
    script_text: str,
    content_prompt: str,
    style: str,
    channel: str,
    region: str,
    scripts_dir: Path,
    prompt_hint: Optional[str],
    script_file: Optional[str],
) -> tuple[bool, str, str, Optional[str]]:
    current_script = script_text
    current_prompt = content_prompt
    current_hint = prompt_hint

    while True:
        decision = _confirm_script(current_script, current_prompt)
        if decision == "y":
            return True, current_script, current_prompt, current_hint
        if decision == "n":
            return False, current_script, current_prompt, current_hint

        print("You selected 'edit'. Update details now:")
        print("  1) Update content hint and regenerate script")
        print("  2) Replace full script text manually")
        print("  3) Regenerate with same settings")
        print("  4) Cancel")
        choice = input("Choose 1/2/3/4: ").strip()

        if choice == "1":
            current_hint = input("Enter new content hint: ").strip() or None
            if script_file:
                print("Regeneration is disabled when --script-file is used. Choose option 2 for manual update.")
                continue
            generated = generate_script(
                style=style,
                channel_name=channel,
                scripts_dir=scripts_dir,
                region=region,
                persist=False,
                prompt_hint=current_hint,
            )
            current_script = generated.script_text
            current_prompt = generated.content_prompt
            continue

        if choice == "2":
            manual_script = input("Enter full script text: ").strip()
            if manual_script:
                current_script = manual_script
            else:
                print("Empty script ignored.")
            continue

        if choice == "3":
            if script_file:
                print("Regeneration is disabled when --script-file is used. Choose option 2 for manual update.")
                continue
            generated = generate_script(
                style=style,
                channel_name=channel,
                scripts_dir=scripts_dir,
                region=region,
                persist=False,
                prompt_hint=current_hint,
            )
            current_script = generated.script_text
            current_prompt = generated.content_prompt
            continue

        if choice == "4":
            return False, current_script, current_prompt, current_hint

        print("Invalid choice. Enter 1, 2, 3, or 4.")


def _apply_pronunciation_overrides(text: str, overrides: dict[str, str]) -> str:
    if not overrides:
        return text
    updated = text
    for src, dst in overrides.items():
        updated = re.sub(rf"\b{re.escape(src)}\b", dst, updated, flags=re.IGNORECASE)
    return updated


def _preview_voice(script_text: str, voice: VoiceConfig, preview_chars: int) -> Path:
    preview_text = script_text.strip()[: max(60, preview_chars)]
    with tempfile.NamedTemporaryFile(prefix="shorts_voice_preview_", suffix=".mp3", delete=False) as tmp:
        preview_path = Path(tmp.name)
    script_to_audio(script_text=preview_text, output_audio=preview_path, voice=voice)
    return preview_path


def _interactive_review_loop(
    *,
    style: str,
    channel: str,
    region: str,
    scripts_dir: Path,
    prompt_hint: Optional[str],
    voice: VoiceConfig,
    preview_chars: int,
) -> tuple[str, str, dict[str, str], bool]:
    current_hint = prompt_hint
    pronunciation_overrides: dict[str, str] = {}

    generated = generate_script(
        style=style,
        channel_name=channel,
        scripts_dir=scripts_dir,
        region=region,
        persist=False,
        prompt_hint=current_hint,
    )
    content_prompt = generated.content_prompt
    script_text = generated.script_text

    while True:
        print("\n--- Content Prompt ---")
        print(content_prompt)
        print("----------------------")
        print("\n--- Script Preview ---")
        print(script_text)
        print("----------------------")
        if pronunciation_overrides:
            print(f"Pronunciation overrides: {pronunciation_overrides}")

        choice_in = input(
            "\nSelect: [a]ccept [h]int-edit [r]egenerate [p]review-voice [m]ap-pronunciation [q]uit: "
        ).strip().lower()

        if choice_in in {"a", "accept"}:
            return content_prompt, script_text, pronunciation_overrides, True
        if choice_in in {"q", "quit"}:
            return content_prompt, script_text, pronunciation_overrides, False
        if choice_in in {"h", "hint"}:
            current_hint = input("Enter new content hint: ").strip() or None
            generated = generate_script(
                style=style,
                channel_name=channel,
                scripts_dir=scripts_dir,
                region=region,
                persist=False,
                prompt_hint=current_hint,
            )
            content_prompt, script_text = generated.content_prompt, generated.script_text
            continue
        if choice_in in {"r", "regenerate"}:
            generated = generate_script(
                style=style,
                channel_name=channel,
                scripts_dir=scripts_dir,
                region=region,
                persist=False,
                prompt_hint=current_hint,
            )
            content_prompt, script_text = generated.content_prompt, generated.script_text
            continue
        if choice_in in {"m", "map"}:
            pair = input("Enter pronunciation override as word=replacement (e.g. scam=स्कैम): ").strip()
            if "=" in pair:
                src, dst = pair.split("=", 1)
                src, dst = src.strip(), dst.strip()
                if src and dst:
                    pronunciation_overrides[src] = dst
            continue
        if choice_in in {"p", "preview"}:
            preview_text = _apply_pronunciation_overrides(script_text, pronunciation_overrides)
            try:
                preview_path = _preview_voice(preview_text, voice=voice, preview_chars=preview_chars)
                print(f"Voice preview generated: {preview_path}")
                print("Play it locally, then continue tuning or accept.")
            except TTSError as exc:
                print(f"Voice preview failed: {exc}")
            continue


def _pick_background_music(paths: AppPaths, explicit_path: Optional[str]) -> Optional[Path]:
    def _history_marker() -> Path:
        return Path(tempfile.gettempdir()) / "shorts_music_history.json"

    def _load_history() -> list[str]:
        marker = _history_marker()
        if not marker.exists():
            return []
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(payload, list):
            return []
        return [str(x) for x in payload if isinstance(x, str)]

    def _save_history(items: list[str]) -> None:
        _history_marker().write_text(json.dumps(items[-200:]), encoding="utf-8")

    if explicit_path:
        p = Path(explicit_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Background music file not found: {p}")
        history = _load_history()
        history.append(str(p))
        _save_history(history)
        return p

    music_dir = paths.assets / "music"
    if not music_dir.exists():
        return None
    candidates = []
    for ext in ("*.mp3", "*.wav", "*.m4a", "*.aac"):
        candidates.extend(music_dir.glob(ext))
    if not candidates:
        return None

    resolved = [p.resolve() for p in candidates]
    history = _load_history()
    used = set(history)
    unused = [p for p in resolved if str(p) not in used]
    if not unused:
        history = []
        unused = resolved
    selected = choice(unused)
    history.append(str(selected))
    _save_history(history)
    return selected


def _warn_if_env_permissions_wide(env_path: Path, logger) -> None:
    if not env_path.exists():
        return
    mode = stat.S_IMODE(env_path.stat().st_mode)
    if mode & 0o077:
        logger.warning(
            ".env permissions are broad (%o). Recommended: chmod 600 .env",
            mode,
        )


def _preflight_capabilities(args: argparse.Namespace, paths: AppPaths, logger) -> str:
    """
    Validate optional capabilities and downgrade gracefully when possible.
    Returns potentially adjusted audio mode.
    """
    audio_mode = args.audio_mode
    if args.ai_visuals and not (get_secret("PEXELS_API_KEY") or get_secret("PIXABAY_API_KEY")):
        logger.info("AI visuals requested but PEXELS/PIXABAY keys missing; using local synthetic visuals only.")

    if os.getenv("OPENAI_PROMPTS_ENABLED", "1").strip().lower() not in {"0", "false", "no"} and not get_secret("OPENAI_API_KEY"):
        logger.info("OPENAI_API_KEY not set; content prompt generation will use local fallback templates.")

    if audio_mode in {"voice", "both"} and not get_secret("ELEVENLABS_API_KEY"):
        logger.info("ELEVENLABS_API_KEY not set; TTS will fallback to edge-tts/macOS/gTTS providers.")

    if audio_mode == "both":
        explicit_music = args.bg_music and Path(args.bg_music).expanduser().exists()
        asset_music_dir = paths.assets / "music"
        has_asset_music = asset_music_dir.exists() and any(asset_music_dir.glob("*.mp3"))
        if not explicit_music and not has_asset_music:
            logger.warning("audio-mode=both but no background music found; auto-switching to voice mode.")
            audio_mode = "voice"

    return audio_mode


def _quality_policy(args: argparse.Namespace) -> tuple[float, bool]:
    """
    Returns:
    - minimum required external scene ratio
    - whether gTTS fallback should be disabled
    """
    mode = args.quality_mode
    if mode == "pro":
        return 0.50, True
    if mode == "balanced":
        return 0.25, False
    return 0.0, False


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

    for p in paths.logs.glob("*"):
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


def _auto_video_title(channel: str, style: str, region: str, script_text: str) -> str:
    style_map = {
        "funny": "फनी शॉर्ट",
        "tech": "टेक टिप",
        "bhakti": "भक्ति विचार",
        "motivation": "प्रेरणा",
        "mirzapuri": "रीजनल शॉर्ट",
        "regional": "रीजनल शॉर्ट",
    }
    style_tag = style_map.get(style, "शॉर्ट वीडियो")
    region_tag = region.strip().title() if region else "Local"
    cleaned = re.sub(r"\s+", " ", script_text.strip())
    cleaned = re.sub(r"[^\w\u0900-\u097F ]+", " ", cleaned)
    cleaned = re.sub(r"\b(नमस्ते|दोस्तों|स्वागत|welcome|hello|हैलो)\b", "", cleaned, flags=re.IGNORECASE)
    words = [w for w in cleaned.split() if len(w) >= 3]
    topic = " ".join(words[:4]).strip()[:40]
    parts = [channel.strip(), style_tag, region_tag]
    if topic:
        parts.append(topic)
    return " | ".join([p for p in parts if p])


def run() -> int:
    args = parse_args()
    paths = AppPaths.discover()
    paths.ensure_directories()
    logger = build_logger(paths.logs / "shorts_factory.log")
    env_path = load_env_and_bind(paths.root.parent)
    _warn_if_env_permissions_wide(env_path, logger)
    effective_audio_mode = _preflight_capabilities(args=args, paths=paths, logger=logger)
    logger.info("Starting run for channel='%s', style='%s'", args.channel, args.style)

    try:
        if not args.keep_history:
            _cleanup_generated_files(paths, logger)

        min_external_scene_ratio, disable_gtts = _quality_policy(args)
        os.environ["SHORTS_DISABLE_GTTS"] = "1" if disable_gtts else "0"

        voice = VoiceConfig(
            language=args.voice_lang,
            tld=args.voice_tld,
            slow=False,
            voice_name=args.voice_name,
        )

        pronunciation_overrides: dict[str, str] = {}
        if args.interactive_review:
            content_prompt, script_text, pronunciation_overrides, approved = _interactive_review_loop(
                style=args.style,
                channel=args.channel,
                region=args.region,
                scripts_dir=paths.scripts,
                prompt_hint=args.content_prompt,
                voice=voice,
                preview_chars=args.preview_chars,
            )
            script_path = None
            if not approved:
                logger.info("Interactive review rejected by user; exiting before TTS/API calls.")
                print("Interactive review ended without approval. No final generation executed.")
                return 0
        else:
            script_text, script_path, content_prompt = load_or_generate_script(
                script_file=args.script_file,
                style=args.style,
                channel=args.channel,
                scripts_dir=paths.scripts,
                region=args.region,
                prompt_hint=args.content_prompt,
            )
        if script_path:
            logger.info("Using script file: %s", script_path)
        else:
            logger.info("Using in-memory generated script (not persisted to disk)")

        if args.review_only:
            print("\n--- Content Prompt ---")
            print(content_prompt)
            print("----------------------\n")
            print(script_text)
            logger.info("Review-only mode enabled; exiting before TTS/API calls.")
            return 0

        if args.review_script:
            approved, script_text, content_prompt, _ = _review_script_with_updates(
                script_text=script_text,
                content_prompt=content_prompt,
                style=args.style,
                channel=args.channel,
                region=args.region,
                scripts_dir=paths.scripts,
                prompt_hint=args.content_prompt,
                script_file=args.script_file,
            )
            if not approved:
                logger.info("Script not approved by user; exiting before TTS/API calls.")
                print("Script rejected. Generation stopped before using TTS/API credits.")
                return 0

        stamp = timestamp_slug()
        audio_path = paths.audio / f"{args.style}_{stamp}.mp3"
        srt_path = paths.output / f"{args.style}_{stamp}.srt"
        video_path = paths.output / f"{args.style}_{stamp}.mp4"
        bg_music = _pick_background_music(paths, args.bg_music)
        if effective_audio_mode in {"music", "both"} and bg_music is None:
            raise FileNotFoundError(
                "Audio mode requires music but no file was provided/found. Use --bg-music or add files in shorts_factory/assets/music."
            )

        timeline_audio = audio_path
        if effective_audio_mode in {"voice", "both"}:
            voice_script_text = _apply_pronunciation_overrides(script_text, pronunciation_overrides)
            script_to_audio(script_text=voice_script_text, output_audio=audio_path, voice=voice)
            logger.info("Audio generated: %s", audio_path)
        else:
            timeline_audio = bg_music
            logger.info("Music-only mode: skipping TTS generation to save credits.")

        subtitles = generate_subtitles(script_text=script_text, audio_file=timeline_audio)
        export_srt = args.with_srt and not args.no_srt
        if export_srt:
            save_srt(subtitles, srt_path)
            logger.info("Subtitles generated: %s", srt_path)
        else:
            logger.info("Skipping sidecar SRT export (audio/video-only mode)")

        if args.background:
            background = Path(args.background).expanduser().resolve()
        else:
            candidates = []
            for ext in ("*.mp4", "*.mov", "*.mkv", "*.webm", "*.jpg", "*.jpeg", "*.png", "*.webp"):
                candidates.extend(paths.assets.glob(ext))
            background = choice(candidates).resolve() if candidates else None
        if background and not background.exists():
            raise FileNotFoundError(f"Background file not found: {background}")

        auto_ai_visuals = args.ai_visuals or bool(get_secret("PEXELS_API_KEY") or get_secret("PIXABAY_API_KEY"))
        if auto_ai_visuals and not args.ai_visuals:
            logger.info("Auto-enabling AI visuals because stock provider API keys are configured.")

        if args.quality_mode == "pro" and effective_audio_mode in {"voice", "both"} and not get_secret("ELEVENLABS_API_KEY"):
            raise ValueError("quality-mode=pro requires ELEVENLABS_API_KEY for high-quality voice.")
        if args.quality_mode == "pro" and not auto_ai_visuals:
            raise ValueError("quality-mode=pro requires PEXELS_API_KEY or PIXABAY_API_KEY for scene visuals.")

        build_short_video(
            audio_path=timeline_audio,
            subtitles=subtitles,
            output_path=video_path,
            background_path=background,
            ai_visuals=auto_ai_visuals,
            assets_dir=paths.assets,
            style=args.style,
            region=args.region,
            audio_mode=effective_audio_mode,
            bg_music_path=bg_music,
            video_title=args.video_title or _auto_video_title(args.channel, args.style, args.region, script_text),
            voice_volume=max(0.0, args.voice_volume),
            bgm_volume=max(0.0, args.bgm_volume),
            min_external_scene_ratio=min_external_scene_ratio if auto_ai_visuals else 0.0,
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
