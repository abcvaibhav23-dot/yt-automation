"""Free text-to-speech using gTTS with stable configuration."""
from __future__ import annotations

from dataclasses import dataclass
import asyncio
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Optional

from gtts import gTTS
import edge_tts
import requests


@dataclass
class VoiceConfig:
    language: str = "en"
    tld: str = "com"
    slow: bool = False
    voice_name: Optional[str] = None


class TTSError(Exception):
    """Raised when TTS conversion fails."""


VOICE_HINTS = {
    "hi": ["Aman", "Soumya", "Lekha", "Neel", "Aditi"],
    "en": ["Samantha", "Daniel", "Alex"],
}

EDGE_VOICE_HINTS = {
    "hi": "hi-IN-SwaraNeural",
    "en": "en-US-AriaNeural",
}

ELEVENLABS_VOICE_HINTS = {
    "hi": "EXAVITQu4vr4xnSDxMaL",
    "en": "EXAVITQu4vr4xnSDxMaL",
}


def _macos_say_to_mp3(script_text: str, output_audio: Path, voice: VoiceConfig) -> Path:
    """Primary local TTS path on macOS using `say` + ffmpeg."""
    normalized_lang = voice.language.split("-")[0].lower()
    preferred = VOICE_HINTS.get(normalized_lang, VOICE_HINTS["en"])
    explicit = voice.voice_name or os.getenv("SHORTS_VOICE_NAME")
    ordered_voices = [explicit] if explicit else []
    ordered_voices.extend([v for v in preferred if v != explicit])

    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
        tmp_aiff = Path(tmp.name)

    try:
        attempted = []
        for name in [*ordered_voices, None]:
            cmd = ["say"]
            if name:
                cmd.extend(["-v", name])
            cmd.extend(["-o", str(tmp_aiff), script_text])
            attempted.append("default" if name is None else name)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                break
        else:
            raise TTSError(f"macOS say failed for voices: {', '.join(attempted)}")

        ffmpeg = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(tmp_aiff),
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "3",
                str(output_audio),
            ],
            capture_output=True,
            text=True,
        )
        if ffmpeg.returncode != 0:
            raise TTSError(f"ffmpeg conversion failed: {ffmpeg.stderr.strip()}")
        if (_probe_audio_duration(output_audio) or 0.0) <= 0.0:
            raise TTSError("Generated audio is empty after macOS say conversion.")
        return output_audio
    finally:
        tmp_aiff.unlink(missing_ok=True)


def _probe_audio_duration(audio_path: Path) -> Optional[float]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _master_audio_in_place(audio_path: Path) -> None:
    tmp_out = audio_path.with_suffix(".mastered.mp3")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-af",
            "highpass=f=80,lowpass=f=14500,acompressor=threshold=-20dB:ratio=3:attack=5:release=60,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(tmp_out),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and tmp_out.exists():
        tmp_out.replace(audio_path)
    else:
        tmp_out.unlink(missing_ok=True)


def _is_audio_likely_silent(audio_path: Path) -> bool:
    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(audio_path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
    if not match:
        return False
    return float(match.group(1)) <= -55.0


def _validate_audio_output(audio_path: Path, source_name: str) -> None:
    duration = _probe_audio_duration(audio_path)
    if not duration or duration <= 0.0:
        raise TTSError(f"{source_name} generated invalid/empty audio.")
    if _is_audio_likely_silent(audio_path):
        raise TTSError(f"{source_name} generated near-silent audio.")


def _gtts_to_mp3(script_text: str, output_audio: Path, voice: VoiceConfig) -> Path:
    tts = gTTS(text=script_text, lang=voice.language, tld=voice.tld, slow=voice.slow)
    tts.save(str(output_audio))
    _master_audio_in_place(output_audio)
    _validate_audio_output(output_audio, "gTTS")
    return output_audio


def _elevenlabs_to_mp3(script_text: str, output_audio: Path, voice: VoiceConfig) -> Path:
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise TTSError("Missing ELEVENLABS_API_KEY")

    lang = voice.language.split("-")[0].lower()
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", ELEVENLABS_VOICE_HINTS.get(lang, ELEVENLABS_VOICE_HINTS["en"]))
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": script_text,
        "model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.8,
            "style": 0.35,
            "use_speaker_boost": True,
        },
    }
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=90)
    except requests.RequestException as exc:
        raise TTSError(f"ElevenLabs request failed: {exc}") from exc

    if response.status_code != 200:
        body_preview = response.text[:240].replace("\n", " ")
        raise TTSError(f"ElevenLabs API error {response.status_code}: {body_preview}")

    output_audio.write_bytes(response.content)
    _master_audio_in_place(output_audio)
    _validate_audio_output(output_audio, "ElevenLabs")
    return output_audio


def _edge_tts_to_mp3(script_text: str, output_audio: Path, voice: VoiceConfig) -> Path:
    lang = voice.language.split("-")[0].lower()
    voice_name = EDGE_VOICE_HINTS.get(lang, EDGE_VOICE_HINTS["en"])

    async def _speak() -> None:
        communicate = edge_tts.Communicate(text=script_text, voice=voice_name, rate="+0%", pitch="+0Hz")
        await communicate.save(str(output_audio))

    asyncio.run(_speak())
    _master_audio_in_place(output_audio)
    _validate_audio_output(output_audio, "edge-tts")
    return output_audio


def script_to_audio(script_text: str, output_audio: Path, voice: VoiceConfig) -> Path:
    """Convert script text to MP3 audio with consistent voice settings."""
    errors = []

    try:
        return _elevenlabs_to_mp3(script_text=script_text, output_audio=output_audio, voice=voice)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ElevenLabs: {exc}")

    try:
        return _edge_tts_to_mp3(script_text=script_text, output_audio=output_audio, voice=voice)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"edge-tts: {exc}")

    try:
        result = _macos_say_to_mp3(script_text=script_text, output_audio=output_audio, voice=voice)
        _master_audio_in_place(output_audio)
        _validate_audio_output(output_audio, "macOS say")
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"macOS say: {exc}")

    try:
        return _gtts_to_mp3(script_text=script_text, output_audio=output_audio, voice=voice)
    except Exception as fallback_exc:  # noqa: BLE001
        errors.append(f"gTTS: {fallback_exc}")

    raise TTSError(" | ".join(errors))
