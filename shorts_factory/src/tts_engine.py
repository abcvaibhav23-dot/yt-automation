"""Free text-to-speech using gTTS with stable configuration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gtts import gTTS


@dataclass
class VoiceConfig:
    language: str = "en"
    tld: str = "com"
    slow: bool = False


class TTSError(Exception):
    """Raised when TTS conversion fails."""


def script_to_audio(script_text: str, output_audio: Path, voice: VoiceConfig) -> Path:
    """Convert script text to MP3 audio with consistent voice settings."""
    try:
        tts = gTTS(text=script_text, lang=voice.language, tld=voice.tld, slow=voice.slow)
        tts.save(str(output_audio))
        return output_audio
    except Exception as exc:  # noqa: BLE001
        raise TTSError(f"Failed to convert text to speech: {exc}") from exc
