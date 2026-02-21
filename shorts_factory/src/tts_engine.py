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
from .secrets_manager import get_secret


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

HINDI_PRONUNCIATION_REPLACEMENTS = {
    "practical": "प्रैक्टिकल",
    "tech": "टेक",
    "update": "अपडेट",
    "short": "शॉर्ट",
    "shorts": "शॉर्ट्स",
    "follow": "फॉलो",
    "comment": "कमेंट",
    "battery": "बैटरी",
    "phone": "फोन",
    "smartphone": "स्मार्टफोन",
    "setting": "सेटिंग",
    "settings": "सेटिंग्स",
    "automation": "ऑटोमेशन",
    "wifi": "वाई-फाई",
    "meeting": "मीटिंग",
    "meetings": "मीटिंग्स",
    "office": "ऑफिस",
    "energy": "एनर्जी",
    "regional": "रीजनल",
    "style": "स्टाइल",
    "confidence": "कॉन्फिडेंस",
    "discipline": "डिसिप्लिन",
    "focus": "फोकस",
    "result": "रिजल्ट",
    "results": "रिजल्ट्स",
    "impact": "इम्पैक्ट",
    "mindset": "माइंडसेट",
    "local": "लोकल",
    "story": "स्टोरी",
    "daily": "डेली",
    "hack": "हैक",
    "hacks": "हैक्स",
    "upi": "यू-पी-आई",
    "api": "ए-पी-आई",
    "ai": "ए-आई",
    "youtube": "यूट्यूब",
    "scam": "स्कैम",
    "fraud": "फ्रॉड",
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
    filter_chain = (
        "highpass=f=70,"
        "lowpass=f=15000,"
        "afftdn=nf=-28,"
        "acompressor=threshold=-19dB:ratio=2.5:attack=8:release=90:makeup=3,"
        "alimiter=limit=0.92,"
        "loudnorm=I=-16:TP=-1.2:LRA=9"
    )
    tmp_out = audio_path.with_suffix(".mastered.mp3")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-af",
            filter_chain,
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


def _audio_db_stats(audio_path: Path) -> tuple[Optional[float], Optional[float]]:
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
        return None, None
    mean_match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
    max_match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
    mean_db = float(mean_match.group(1)) if mean_match else None
    max_db = float(max_match.group(1)) if max_match else None
    return mean_db, max_db


def _audio_quality_score(audio_path: Path) -> float:
    duration = _probe_audio_duration(audio_path) or 0.0
    mean_db, max_db = _audio_db_stats(audio_path)
    if duration <= 0.0 or mean_db is None or max_db is None:
        return -999.0

    # Closer to natural loudness and safe peak gets higher score.
    mean_penalty = abs(mean_db - (-18.0)) * 1.3
    peak_penalty = abs(max_db - (-3.0)) * 2.2
    short_penalty = 20.0 if duration < 4.0 else 0.0
    return 100.0 - mean_penalty - peak_penalty - short_penalty


def _candidate_elevenlabs_voice_ids(lang: str) -> list[str]:
    ids: list[str] = []

    env_list = os.getenv(f"ELEVENLABS_VOICE_IDS_{lang.upper()}", "").strip()
    if env_list:
        ids.extend([x.strip() for x in env_list.split(",") if x.strip()])

    specific = os.getenv(f"ELEVENLABS_VOICE_ID_{lang.upper()}", "").strip()
    if specific:
        ids.append(specific)

    generic = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    if generic:
        ids.append(generic)

    fallback = ELEVENLABS_VOICE_HINTS.get(lang, ELEVENLABS_VOICE_HINTS["en"])
    ids.append(fallback)

    # de-duplicate preserving order
    deduped: list[str] = []
    seen = set()
    for vid in ids:
        if vid and vid not in seen:
            seen.add(vid)
            deduped.append(vid)
    return deduped


def _prepare_tts_text(script_text: str, voice: VoiceConfig) -> str:
    def _normalize_common(text: str) -> str:
        out = text.strip()
        # Remove bracketed visual cues so TTS speaks content only.
        out = re.sub(r"\[[^\]]{1,120}\]", " ", out)
        # Remove leaked metadata from older script formats.
        out = re.sub(r"थीम इनपुट:\s*.*?(?=आज का फोकस:|$)", " ", out, flags=re.IGNORECASE)
        out = re.sub(r"\s+", " ", out).strip()
        return out

    def _normalize_hindi_symbols(text: str) -> str:
        out = text
        out = re.sub(r"(\d+)\s*%", r"\1 प्रतिशत", out)
        out = out.replace("&", " और ")
        out = out.replace("@", " ऐट ")
        out = out.replace("/", " ")
        out = re.sub(r"\s+", " ", out).strip()
        return out

    lang = voice.language.split("-")[0].lower()
    normalized = _normalize_common(script_text)
    if lang != "hi" or not normalized:
        return normalized

    processed = _normalize_hindi_symbols(normalized)
    for src, dst in HINDI_PRONUNCIATION_REPLACEMENTS.items():
        processed = re.sub(rf"\b{re.escape(src)}\b", dst, processed, flags=re.IGNORECASE)

    # Convert standalone uppercase acronyms to Hindi letter-like pauses (e.g. GDP -> जी-डी-पी).
    def _acronym_to_hindi(match: re.Match) -> str:
        token = match.group(0)
        letters = []
        for ch in token:
            upper = ch.upper()
            letters.append(
                {
                    "A": "ए",
                    "B": "बी",
                    "C": "सी",
                    "D": "डी",
                    "E": "ई",
                    "F": "एफ",
                    "G": "जी",
                    "H": "एच",
                    "I": "आई",
                    "J": "जे",
                    "K": "के",
                    "L": "एल",
                    "M": "एम",
                    "N": "एन",
                    "O": "ओ",
                    "P": "पी",
                    "Q": "क्यू",
                    "R": "आर",
                    "S": "एस",
                    "T": "टी",
                    "U": "यू",
                    "V": "वी",
                    "W": "डब्ल्यू",
                    "X": "एक्स",
                    "Y": "वाई",
                    "Z": "ज़ेड",
                }.get(upper, ch)
            )
        return "-".join(letters)

    processed = re.sub(r"\b[A-Z]{2,}\b", _acronym_to_hindi, processed)
    # Add subtle pause hints for better prosody.
    processed = re.sub(r"\s*\.\.\.\s*", "... ", processed)
    processed = re.sub(r"\s+", " ", processed).strip()
    return processed


def _gtts_to_mp3(script_text: str, output_audio: Path, voice: VoiceConfig) -> Path:
    tts = gTTS(text=script_text, lang=voice.language, tld=voice.tld, slow=voice.slow)
    tts.save(str(output_audio))
    _master_audio_in_place(output_audio)
    _validate_audio_output(output_audio, "gTTS")
    return output_audio


def _elevenlabs_to_mp3(script_text: str, output_audio: Path, voice: VoiceConfig) -> Path:
    api_key = get_secret("ELEVENLABS_API_KEY")
    if not api_key:
        raise TTSError("Missing ELEVENLABS_API_KEY")

    lang = voice.language.split("-")[0].lower()
    candidate_voice_ids = _candidate_elevenlabs_voice_ids(lang)
    max_attempts = int(os.getenv("ELEVENLABS_MAX_RETRIES", "2"))
    if lang == "hi":
        max_attempts = max(2, max_attempts)
    else:
        max_attempts = max(1, max_attempts)
    candidate_voice_ids = candidate_voice_ids[:max_attempts]

    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    payload_base = {
        "text": script_text,
        "model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
    }

    best_score = -999.0
    best_audio_bytes: Optional[bytes] = None
    errors = []
    for idx, voice_id in enumerate(candidate_voice_ids):
        # later attempts push stability slightly up for clearer articulation
        stability = min(0.78, 0.50 + idx * 0.10)
        payload = {
            **payload_base,
            "output_format": "mp3_44100_192",
            "voice_settings": {
                "stability": stability,
                "similarity_boost": 0.88,
                "style": 0.10,
                "use_speaker_boost": True,
            },
        }
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=90)
        except requests.RequestException as exc:
            errors.append(f"{voice_id}: {exc}")
            continue

        if response.status_code != 200:
            body_preview = response.text[:180].replace("\n", " ")
            errors.append(f"{voice_id}: HTTP {response.status_code} {body_preview}")
            continue

        output_audio.write_bytes(response.content)
        _master_audio_in_place(output_audio)
        try:
            _validate_audio_output(output_audio, f"ElevenLabs({voice_id})")
        except TTSError as exc:
            errors.append(str(exc))
            continue

        score = _audio_quality_score(output_audio)
        if score > best_score:
            best_score = score
            best_audio_bytes = output_audio.read_bytes()

        # Good enough; stop early to preserve credits.
        if score >= 85.0:
            return output_audio

    if best_audio_bytes:
        output_audio.write_bytes(best_audio_bytes)
        _validate_audio_output(output_audio, "ElevenLabs(best)")
        return output_audio

    raise TTSError(f"ElevenLabs retries failed: {' | '.join(errors)}")


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
    prepared_text = _prepare_tts_text(script_text=script_text, voice=voice)
    errors = []

    try:
        return _elevenlabs_to_mp3(script_text=prepared_text, output_audio=output_audio, voice=voice)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ElevenLabs: {exc}")

    try:
        return _edge_tts_to_mp3(script_text=prepared_text, output_audio=output_audio, voice=voice)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"edge-tts: {exc}")

    try:
        result = _macos_say_to_mp3(script_text=prepared_text, output_audio=output_audio, voice=voice)
        _master_audio_in_place(output_audio)
        _validate_audio_output(output_audio, "macOS say")
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"macOS say: {exc}")

    disable_gtts = os.getenv("SHORTS_DISABLE_GTTS", "0").strip().lower() in {"1", "true", "yes"}
    if not disable_gtts:
        try:
            return _gtts_to_mp3(script_text=prepared_text, output_audio=output_audio, voice=voice)
        except Exception as fallback_exc:  # noqa: BLE001
            errors.append(f"gTTS: {fallback_exc}")
    else:
        errors.append("gTTS: disabled by SHORTS_DISABLE_GTTS")

    raise TTSError(" | ".join(errors))
