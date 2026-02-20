# Shorts Factory (YouTube Shorts Automation)

Production-style local automation project to generate daily Shorts for multiple channels (Tech, Funny, Bhakti/Motivation, Mirzapuri).

## 1) Project Structure

```text
shorts_factory/
├── assets/                  # Background image/video files (input)
├── audio/                   # Generated TTS audio files
├── logs/                    # Runtime logs
├── output/                  # Final MP4 + SRT files
├── scripts/                 # Script text files
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── logger_setup.py
│   ├── main.py
│   ├── script_generator.py
│   ├── subtitle_generator.py
│   ├── tts_engine.py
│   └── video_builder.py
└── __init__.py
```

## 2) Requirements

- Python **3.9+**
- `ffmpeg` installed on macOS
- Dependencies in `requirements.txt`

Install ffmpeg (macOS):

```bash
brew install ffmpeg
```

Install Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3) Step-by-Step Implementation Flow

1. `script_generator.py` creates style-based script text.
2. `tts_engine.py` converts script to MP3 using free `gTTS` with fixed language + TLD (same voice profile each day).
3. `subtitle_generator.py` reads MP3 duration and creates timed subtitle chunks + `.srt`.
4. `video_builder.py` builds vertical 9:16 MP4 using optional background media and subtitle overlays.
5. `main.py` orchestrates all steps with logging and error handling.

## 4) Run Commands (macOS Terminal)

### Auto-generate script and video

```bash
python -m shorts_factory.src.main \
  --channel "Tech Daily" \
  --style tech \
  --background shorts_factory/assets/bg.mp4
```

### Use existing script file

```bash
python -m shorts_factory.src.main \
  --channel "Bhakti Vibes" \
  --style bhakti \
  --script-file shorts_factory/scripts/custom_script.txt \
  --background shorts_factory/assets/bg.jpg
```

### Mirzapuri style with Hindi voice variant

```bash
python -m shorts_factory.src.main \
  --channel "Mirzapuri Adda" \
  --style mirzapuri \
  --voice-lang hi \
  --voice-tld co.in
```

## 5) Output Files

- Final video: `shorts_factory/output/<style>_<timestamp>.mp4`
- Subtitles: `shorts_factory/output/<style>_<timestamp>.srt`
- Audio: `shorts_factory/audio/<style>_<timestamp>.mp3`
- Logs: `shorts_factory/logs/shorts_factory.log`

## 6) Error Handling + Logging

- Known errors handled:
  - Missing script/background file
  - Empty script
  - TTS conversion failure
- Unknown errors are caught and logged with traceback.
- Log format: `timestamp | level | logger | message`

## 7) Notes on Subtitle Auto-Generation

- Script is split into word chunks (default 5 words/chunk).
- Audio total duration is read from MP3 metadata.
- Duration is equally distributed across subtitle chunks.
- SRT is exported automatically.

## 8) Optional Improvements

- Add Coqui TTS offline model for network-free voice generation.
- Add channel-specific branding overlays and watermark.
- Add scheduler (cron/launchd) for daily auto generation.
- Add script source plugins (RSS, markdown prompts, CSV ideas).
- Add batch mode to generate 2–3 videos per channel automatically.
