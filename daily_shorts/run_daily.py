"""
README-style quick start:
1) python3 -m venv venv
2) source venv/bin/activate
3) pip install -r requirements.txt
4) python run_daily.py --channel tech
"""
from __future__ import annotations

import argparse
import json
import random
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from config.settings import (
    CLEAN_CACHE_BY_RUN,
    CACHE_MAX_AGE_DAYS,
    DATA_DIR,
    ELEVENLABS_API_KEY,
    FINAL_DIR,
    FFMPEG_BINARY,
    KEEP_FINAL_RUNS_PER_CHANNEL,
    KEEP_LOG_FILES,
    LOG_DIR,
    MUSIC_DIR,
    OUTPUT_DIR,
    PEXELS_API_KEY,
    PIXABAY_API_KEY,
    PROMPTS_DIR,
)
from core.duplicate_manager import DuplicateManager
from core.cleanup_manager import perform_post_run_cleanup
from core.hook_rewriter import rewrite_best_hook
from core.logger import build_logger
from core.media_fetcher import MediaFetcher
from core.metadata_generator import build_metadata, save_metadata
from core.retention_scorer import score_script
from core.script_generator import generate_script
from core.subtitle_engine import build_subtitles, save_srt
from core.thumbnail_generator import create_thumbnail
from core.tts_engine import TTSEngine
from core.video_assembler import VideoAssembler


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily YouTube Shorts automation")
    p.add_argument("--channel", required=True, choices=["tech", "funny", "bhakti", "mirzapuri"])
    p.add_argument("--auto-approve", action="store_true", help="Skip y/n review confirmation")
    p.add_argument("--prompt-file", type=str, default=None, help="Optional custom prompt file path.")
    p.add_argument("--prompt-text", type=str, default=None, help="Optional inline prompt text override.")
    p.add_argument("--prompt-append", type=str, default=None, help="Optional extra prompt instructions to append.")
    p.add_argument("--edit-prompt", action="store_true", help="Interactively edit prompt before script generation.")
    p.add_argument("--allow-no-review", action="store_true", help="Allow generation without interactive review confirmation.")
    return p.parse_args()


def load_channels(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_topics(path: Path) -> List[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def choose_topic(topics: List[str], dm: DuplicateManager) -> str:
    fresh = [t for t in topics if not dm.topic_used(t)]
    pool = fresh if fresh else topics
    return random.choice(pool)


def choose_music(mood: str) -> Path:
    candidates = list(MUSIC_DIR.glob(f"*{mood}*.mp3")) + list(MUSIC_DIR.glob("*.mp3"))
    if candidates:
        return random.choice(candidates)

    # Create fallback local music loop when assets are empty.
    fallback = MUSIC_DIR / f"fallback_{mood}.mp3"
    cmd = [
        FFMPEG_BINARY,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=140:duration=45",
        "-f",
        "lavfi",
        "-i",
        "anoisesrc=color=pink:amplitude=0.02:duration=45",
        "-filter_complex",
        "[0:a]volume=0.14[a0];[1:a]lowpass=f=4200,highpass=f=120,volume=0.05[a1];[a0][a1]amix=inputs=2,loudnorm=I=-20:TP=-2:LRA=9",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(fallback),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return fallback


def _require_host_dns(host: str, service_name: str) -> None:
    try:
        socket.getaddrinfo(host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RuntimeError(f"{service_name} is unreachable (DNS failed for {host}). Check internet/VPN/firewall.") from exc


def print_review(script: Dict, score_payload: Dict, topic: str, hook_variant: str) -> None:
    print("\n========== MANUAL REVIEW ==========")
    print(f"Title: {script['title']}")
    print(f"Topic: {topic}")
    print(f"Hook score: {score_payload['score']}")
    print(f"Hook used: {hook_variant}")
    print(f"Estimated duration: {script['total_duration']}s")
    print("\nScenes:")
    for i, s in enumerate(script["scenes"], start=1):
        print(f"  {i}. {s['text']}")
    all_keywords = sorted({k for s in script["scenes"] for k in s.get("keywords", [])})
    print(f"\nKeywords: {', '.join(all_keywords)}")
    print("===================================\n")


def ask_continue_confirmation() -> str:
    while True:
        ans = input(
            "Continue to generate voice, fetch media, and render final video? "
            "[y=Yes / e=Edit / n=No]: "
        ).strip().lower()
        if ans in {"y", "yes"}:
            return "y"
        if ans in {"e", "edit"}:
            return "e"
        if ans in {"n", "no"}:
            return "n"
        print("Please enter 'y', 'e', or 'n'.")


def ask_review_update_action() -> str:
    print("\nUpdate options:")
    print("  1) Append extra prompt instruction")
    print("  2) Replace full prompt text")
    print("  3) Change topic")
    print("  4) Regenerate with same settings")
    print("  5) Cancel run")
    while True:
        action = input("Choose 1/2/3/4/5: ").strip()
        if action in {"1", "2", "3", "4", "5"}:
            return action
        print("Invalid choice. Enter 1, 2, 3, 4, or 5.")


def resolve_prompt_text(args: argparse.Namespace, default_prompt_path: Path) -> str:
    if args.prompt_text and args.prompt_text.strip():
        prompt = args.prompt_text.strip()
    elif args.prompt_file:
        custom = Path(args.prompt_file).expanduser().resolve()
        if not custom.exists():
            raise FileNotFoundError(f"Custom prompt file not found: {custom}")
        prompt = custom.read_text(encoding="utf-8")
    else:
        prompt = default_prompt_path.read_text(encoding="utf-8")

    if args.prompt_append and args.prompt_append.strip():
        prompt = f"{prompt.rstrip()}\n\nAdditional instructions:\n{args.prompt_append.strip()}\n"

    if args.edit_prompt:
        print("\n--- Current Prompt ---")
        print(prompt)
        print("----------------------")
        print("Prompt edit mode: leave blank to keep as-is.")
        edited = input("Enter revised prompt (single-line edit): ").strip()
        if edited:
            prompt = edited
    return prompt


def _retention_rescue(script: Dict, topic: str) -> Dict:
    """
    Deterministically strengthen hook + CTA with scorer-friendly terms
    when score remains too low after normal hook rewriting.
    """
    scenes = script.get("scenes", [])
    if not scenes:
        return script
    strong_hook = (
        f"Wait... secret truth: {topic} ki sabse badi mistake kya hai, "
        "and why result fail hota hai?"
    )
    scenes[0]["text"] = strong_hook
    cta_options = [
        "Follow, share, comment aur save karo.",
        "Comment karo, share karo, aur next part ke liye follow karo.",
        "Agar line hit ki ho toh save + follow abhi karo.",
    ]
    cta_tail = random.choice(cta_options)
    if scenes[-1].get("text"):
        low = scenes[-1]["text"].lower()
        if not any(x in low for x in ["follow", "share", "comment", "save"]):
            scenes[-1]["text"] = f"{scenes[-1]['text']} {cta_tail}"
    else:
        scenes[-1]["text"] = cta_tail
    script["scenes"] = scenes
    return script


def main() -> int:
    args = parse_args()
    run_started_at = datetime.utcnow()
    ts = run_started_at.strftime("%Y%m%d_%H%M%S")
    logger = build_logger(LOG_DIR / f"run_{ts}.log")
    start = time.time()

    channels = load_channels(Path(__file__).resolve().parent / "config" / "channels.json")
    cfg = channels[args.channel]
    if args.auto_approve and not args.allow_no_review:
        print("Error: Prompt/script review is mandatory. Remove --auto-approve or pass --allow-no-review explicitly.", file=sys.stderr)
        return 1
    if not ELEVENLABS_API_KEY:
        print("Error: ELEVENLABS_API_KEY is required for voice generation.", file=sys.stderr)
        return 1
    if not PIXABAY_API_KEY and not PEXELS_API_KEY:
        print("Error: PIXABAY_API_KEY or PEXELS_API_KEY is required for media fetching.", file=sys.stderr)
        return 1
    try:
        _require_host_dns("api.elevenlabs.io", "ElevenLabs")
    except RuntimeError as exc:
        print(f"Warning: {exc} Falling back to local TTS where possible.", file=sys.stderr)

    dm = DuplicateManager(DATA_DIR / "history.json", DATA_DIR / "used_keywords.json", cooldown_days=3)
    topics = load_topics(DATA_DIR / "topics.txt")
    topic = choose_topic(topics, dm)

    prompt_text = resolve_prompt_text(args, PROMPTS_DIR / cfg["prompt_file"])
    try:
        hook_api_calls = 0
        while True:
            script_res = generate_script(
                channel=args.channel,
                language_mode=cfg["language_mode"],
                prompt_text=prompt_text,
                topics=[topic],
                max_scenes=int(cfg["max_scenes"]),
            )
            script = script_res.payload
            if script_res.api_calls == 0:
                logger.info("OpenAI API key not configured or unavailable; using local fallback script generator.")

            score_payload = score_script(script)
            hook_variant = script["scenes"][0]["text"]

            if score_payload["score"] < int(cfg["hook_threshold_score"]):
                logger.info("Score below threshold (%s < %s), rewriting hook", score_payload["score"], cfg["hook_threshold_score"])
                script, hook_variant, extra_calls = rewrite_best_hook(script, topic=topic, language_mode=cfg["language_mode"])
                hook_api_calls += extra_calls
                score_payload = score_script(script)
            if score_payload["score"] <= 70:
                script, hook_variant, extra_calls = rewrite_best_hook(script, topic=topic, language_mode=cfg["language_mode"])
                hook_api_calls += extra_calls
                score_payload = score_script(script)
            if score_payload["score"] <= 70:
                script, hook_variant, extra_calls = rewrite_best_hook(script, topic=topic, language_mode=cfg["language_mode"])
                hook_api_calls += extra_calls
                score_payload = score_script(script)
            if score_payload["score"] <= 70:
                logger.info("Applying retention rescue because hook score is still low (%s).", score_payload["score"])
                script = _retention_rescue(script, topic=topic)
                hook_variant = script["scenes"][0]["text"]
                score_payload = score_script(script)
            if score_payload["score"] <= 70:
                raise RuntimeError(
                    f"Hook score must be >70, got {score_payload['score']}. "
                    "Use --prompt-append or --edit-prompt to strengthen hook."
                )

            print_review(script, score_payload, topic, hook_variant)
            if args.auto_approve:
                break

            decision = ask_continue_confirmation()
            if decision == "y":
                break
            if decision == "n":
                logger.info("Run cancelled by user during review confirmation")
                print("Cancelled.")
                return 0

            action = ask_review_update_action()
            if action == "1":
                extra = input("Add extra prompt instruction: ").strip()
                if extra:
                    prompt_text = f"{prompt_text.rstrip()}\n\nAdditional instructions:\n{extra}\n"
            elif action == "2":
                new_prompt = input("Enter full prompt text: ").strip()
                if new_prompt:
                    prompt_text = new_prompt
            elif action == "3":
                new_topic = input("Enter new topic: ").strip()
                if new_topic:
                    topic = new_topic
            elif action == "4":
                pass
            else:
                logger.info("Run cancelled by user during review update flow")
                print("Cancelled.")
                return 0

        # Voice generation
        output_audio = OUTPUT_DIR / f"{args.channel}_{ts}.mp3"
        tts = TTSEngine(cache_dir=(Path(__file__).resolve().parent / "assets" / "cache"))
        tts_res = tts.generate(
            scenes=script["scenes"],
            voice_id=cfg["elevenlabs_voice_id"],
            language_mode=cfg["language_mode"],
            output_audio=output_audio,
        )

        # Subtitles
        subtitles = build_subtitles(script["scenes"], tts_res.durations)
        srt_path = OUTPUT_DIR / f"{args.channel}_{ts}.srt"
        save_srt(subtitles, srt_path)

        # Media fetching
        media = MediaFetcher(cache_dir=(Path(__file__).resolve().parent / "assets" / "cache"), keywords_db_path=DATA_DIR / "used_keywords.json")
        all_keywords = [k for s in script["scenes"] for k in s.get("keywords", [])]
        allowed = dm.filter_keywords(all_keywords)
        clip_infos = media.fetch_scene_clips(script["scenes"], allowed_keywords=allowed)

        # Video assemble
        music = choose_music(cfg["music_mood"])
        out_video = OUTPUT_DIR / f"{args.channel}_{ts}.mp4"
        assembler = VideoAssembler(size=(1080, 1920), fps=30)
        assembler.assemble(
            scene_clips=[c.path for c in clip_infos],
            scene_durations=tts_res.durations,
            voice_audio=tts_res.merged_audio,
            bg_music=music,
            subtitles=subtitles,
            title=script["title"],
            out_path=out_video,
        )

        # Thumbnail
        thumb_path = OUTPUT_DIR / f"{args.channel}_{ts}.png"
        create_thumbnail(out_video, script["title"], thumb_path)

        # Metadata
        metadata = build_metadata(
            channel=args.channel,
            title=script["title"],
            topic=topic,
            keywords=all_keywords,
        )
        meta_path = OUTPUT_DIR / f"{args.channel}_{ts}_metadata.json"
        save_metadata(meta_path, metadata)

        # Final bundle
        bundle_dir = FINAL_DIR / f"{args.channel}_{ts}"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        for p in [out_video, output_audio, srt_path, thumb_path, meta_path]:
            p.replace(bundle_dir / p.name)

        dm.record_keywords(all_keywords)
        api_calls = {
            "openai": script_res.api_calls + hook_api_calls,
            "elevenlabs": tts_res.api_calls,
            "pixabay": media.api_calls["pixabay"],
            "pexels": media.api_calls["pexels"],
        }
        dm.record_run(
            topic=topic,
            channel=args.channel,
            score=score_payload["score"],
            hook_variant=hook_variant,
            scene_texts=[str(s.get("text", "")).strip() for s in script.get("scenes", [])],
            duration=sum(tts_res.durations),
            api_calls=api_calls,
        )

        render_time = round(time.time() - start, 2)
        logger.info("Channel=%s Topic=%s Score=%s Hook=%s Duration=%.2fs API=%s RenderTime=%ss",
                    args.channel, topic, score_payload["score"], hook_variant, sum(tts_res.durations), api_calls, render_time)
        cleanup_report = perform_post_run_cleanup(
            channel=args.channel,
            keep_runs_per_channel=KEEP_FINAL_RUNS_PER_CHANNEL,
            keep_log_files=KEEP_LOG_FILES,
            cache_max_age_days=CACHE_MAX_AGE_DAYS,
            clean_cache_by_run=CLEAN_CACHE_BY_RUN,
            run_started_at=run_started_at,
            keep_current_bundle=bundle_dir,
        )
        logger.info(
            "Auto-cleanup completed. Removed files=%s dirs=%s",
            cleanup_report.removed_files,
            cleanup_report.removed_dirs,
        )

        print(f"Done. Final files: {bundle_dir}")
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("Run failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
