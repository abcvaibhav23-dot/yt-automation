# Shorts Factory (YouTube Shorts Automation)

Pipeline for generating vertical Shorts with:
- style-based script generation
- natural voice TTS (ElevenLabs -> edge-tts -> macOS say -> gTTS)
- subtitle-timed scene composition
- royalty-free visual providers (Pexels/Pixabay) with fallback visuals

## Requirements

- Python 3.9+
- ffmpeg

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## API Keys (Recommended)

Set these env vars for best quality:

```bash
export ELEVENLABS_API_KEY="..."
export ELEVENLABS_VOICE_ID="..."   # optional
export ELEVENLABS_MODEL_ID="eleven_multilingual_v2"  # optional
export PEXELS_API_KEY="..."
export PIXABAY_API_KEY="..."
```

If any provider is missing/unavailable, the code automatically falls back.

## Run

```bash
.venv/bin/python -m shorts_factory.src.main \
  --channel "UP-Bihar Shorts" \
  --style regional \
  --region sonbhadra \
  --voice-lang hi \
  --ai-visuals \
  --no-srt
```

### Generate all four styles

```bash
./generate_all.sh
# optional region:
./generate_all.sh sonbhadra
```

## Fresh-Run Behavior (Default)

By default each run deletes old generated artifacts before creating new output:
- `shorts_factory/scripts` generated dated scripts
- `shorts_factory/audio/*`
- `shorts_factory/output/*`
- `shorts_factory/assets/scene_cache/*`

Use `--keep-history` to disable cleanup.

## Output

- Video: `shorts_factory/output/<style>_<timestamp>.mp4`
- Audio: `shorts_factory/audio/<style>_<timestamp>.mp3`
- Optional sidecar SRT: `shorts_factory/output/<style>_<timestamp>.srt`
- Media usage report: `shorts_factory/output/<style>_<timestamp>.credits.txt`

## Copyright Risk Note

This pipeline uses royalty-free providers, but no system can guarantee zero copyright claims forever. Platform policy changes and third-party disputes can still happen. Always review current provider license terms and keep the generated `.credits.txt` file.
