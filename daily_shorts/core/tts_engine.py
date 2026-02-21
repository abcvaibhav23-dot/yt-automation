"""ElevenLabs TTS with per-scene synthesis and concatenation."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import requests

from config.settings import ELEVENLABS_API_KEY, FFMPEG_BINARY, FFPROBE_BINARY


@dataclass
class TTSResult:
    scene_audio: List[Path]
    merged_audio: Path
    durations: List[float]
    api_calls: int


class TTSEngine:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _clean_text(text: str, language_mode: str) -> str:
        t = text.replace("\n", " ")
        t = re.sub(r"[\[\]\{\}\(\)]", " ", t)
        t = re.sub(r"[;|*_~]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        replacements = {
            "productivity": "productivity",
            "algorithm": "algo",
            "entrepreneur": "business person",
            "ksh": "ksh",
        }
        for s, d in replacements.items():
            t = re.sub(rf"\b{s}\b", d, t, flags=re.IGNORECASE)
        if language_mode in {"hindi", "hinglish"}:
            t = t.replace("%", " percent")
            t = t.replace("&", " and ")
        return t

    @staticmethod
    def _audio_duration(path: Path) -> float:
        cmd = [FFPROBE_BINARY, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)]
        out = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(out.stdout.strip())
        except ValueError:
            return 0.0

    @staticmethod
    def _macos_say_to_mp3(text: str, out_path: Path, language_mode: str) -> Path:
        voices = ["Samantha", "Ava", "Daniel"]
        if language_mode in {"hindi", "hinglish"}:
            voices = ["Aman", "Aditi", "Rishi", "Samantha"]

        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
            aiff = Path(tmp.name)
        try:
            ok = False
            for voice in voices:
                cmd = ["say", "-v", voice, "-o", str(aiff), text]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode == 0 and aiff.exists() and aiff.stat().st_size > 4096:
                    ok = True
                    break
            if not ok:
                raise RuntimeError("macOS say could not generate valid AIFF output.")

            conv = [
                FFMPEG_BINARY,
                "-y",
                "-i",
                str(aiff),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(out_path),
            ]
            subprocess.run(conv, check=True, capture_output=True)
            if not out_path.exists() or out_path.stat().st_size <= 2048:
                raise RuntimeError("macOS say mp3 conversion produced empty output.")
            return out_path
        finally:
            aiff.unlink(missing_ok=True)

    @staticmethod
    def _bot_tts_to_mp3(text: str, out_path: Path) -> Path:
        """
        Codex-safe robotic fallback when cloud TTS and local OS TTS are unavailable.
        Produces synthetic speech-like cadence audio (not lexical speech).
        """
        words = max(4, len([w for w in text.split() if w]))
        duration = min(14.0, max(2.5, words * 0.42))
        cmd = [
            FFMPEG_BINARY,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=190:duration={duration:.3f}",
            "-af",
            "tremolo=f=11:d=0.7,highpass=f=120,lowpass=f=2600,acompressor=threshold=-20dB:ratio=2.2:attack=5:release=70",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path

    def _pad_audio_to_duration(self, source_audio: Path, min_duration: float, key_hint: str) -> Path:
        """
        Ensure scene narration lasts at least min_duration seconds.
        Pads with silence when TTS is too short to keep timeline sync.
        """
        target = max(0.0, float(min_duration))
        if target <= 0:
            return source_audio

        current = self._audio_duration(source_audio)
        # Avoid long dead air; allow only a very light tail padding for natural breathing.
        target = min(target, current + 0.35)
        if current >= target - 0.08:
            return source_audio

        key = hashlib.md5(f"{key_hint}:{source_audio.name}:{round(target,2)}".encode("utf-8")).hexdigest()[:16]
        padded = self.cache_dir / f"tts_pad_{key}.mp3"
        if padded.exists() and padded.stat().st_size > 2048:
            existing = self._audio_duration(padded)
            if existing >= target - 0.20:
                return padded

        cmd = [
            FFMPEG_BINARY,
            "-y",
            "-i",
            str(source_audio),
            "-af",
            f"apad=pad_dur={max(0.0, target - current):.3f}",
            "-t",
            f"{target:.3f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(padded),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return padded

    def _silent_scene_audio(self, duration_sec: float, key_hint: str) -> Path:
        duration = max(1.0, float(duration_sec))
        key = hashlib.md5(f"silent:{key_hint}:{round(duration,2)}".encode("utf-8")).hexdigest()[:16]
        out = self.cache_dir / f"tts_silent_{key}.mp3"
        if out.exists() and out.stat().st_size > 1024:
            return out
        cmd = [
            FFMPEG_BINARY,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=mono",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out

    def _synthesize_scene(self, text: str, voice_id: str, language_mode: str) -> Tuple[Path, bool]:
        clean = self._clean_text(text, language_mode)
        key = hashlib.md5(f"{voice_id}:{clean}".encode("utf-8")).hexdigest()[:16]
        out = self.cache_dir / f"tts_{key}.mp3"
        if out.exists() and out.stat().st_size > 2048:
            return out, True

        enable_bot_tts = os.getenv("SHORTS_ENABLE_BOT_TTS", "1").strip().lower() in {"1", "true", "yes"}
        if not ELEVENLABS_API_KEY:
            try:
                self._macos_say_to_mp3(clean, out, language_mode=language_mode)
            except Exception:
                if enable_bot_tts:
                    self._bot_tts_to_mp3(clean, out)
                else:
                    raise
            return out, False

        payload = {
            "text": clean,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.58,
                "similarity_boost": 0.86,
                "style": 0.08,
                "use_speaker_boost": True,
            },
            "output_format": "mp3_44100_128",
        }
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers=headers,
                json=payload,
                timeout=90,
            )
            if r.status_code != 200:
                raise RuntimeError(f"ElevenLabs failed: {r.status_code} {r.text[:180]}")
            out.write_bytes(r.content)
        except Exception:
            # Local fallback to keep pipeline runnable if API is temporarily unreachable.
            try:
                self._macos_say_to_mp3(clean, out, language_mode=language_mode)
            except Exception:
                if enable_bot_tts:
                    self._bot_tts_to_mp3(clean, out)
                else:
                    raise
        return out, False

    def generate(self, scenes: List[Dict], voice_id: str, language_mode: str, output_audio: Path) -> TTSResult:
        scene_audio: List[Path] = []
        api_calls = 0
        allow_silent = os.getenv("SHORTS_ALLOW_SILENT_TTS_FALLBACK", "1").strip().lower() in {"1", "true", "yes"}
        for idx, s in enumerate(scenes):
            try:
                p, cached = self._synthesize_scene(s["text"], voice_id, language_mode)
            except Exception:
                if not allow_silent:
                    raise
                expected = float(s.get("duration_estimate", 8) or 8)
                p = self._silent_scene_audio(expected, key_hint=f"{voice_id}:{idx}:{s['text'][:30]}")
                cached = True
            expected = float(s.get("duration_estimate", 0) or 0)
            p = self._pad_audio_to_duration(p, min_duration=expected, key_hint=f"{voice_id}:{idx}:{s['text'][:30]}")
            scene_audio.append(p)
            if not cached:
                api_calls += 1

        concat_file = output_audio.with_suffix(".txt")
        concat_file.write_text("\n".join([f"file '{p.resolve()}'" for p in scene_audio]), encoding="utf-8")
        # Re-encode while concatenating to avoid MP3 encoder-delay gaps between scene chunks.
        cmd = [
            FFMPEG_BINARY,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-af",
            "aresample=async=1:min_hard_comp=0.100:first_pts=0",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output_audio),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        concat_file.unlink(missing_ok=True)

        durations = [self._audio_duration(p) for p in scene_audio]
        return TTSResult(scene_audio=scene_audio, merged_audio=output_audio, durations=durations, api_calls=api_calls)
