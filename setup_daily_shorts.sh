#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${ROOT_DIR}/daily_shorts"
VENV_DIR="${ROOT_DIR}/.venv"
APP_ENV="${APP_DIR}/.env"
ROOT_ENV="${ROOT_DIR}/.env"
RUN_CHANNEL=""
MUSIC_DIR="${APP_DIR}/assets/music"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)
      RUN_CHANNEL="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--run <tech|funny|bhakti|mirzapuri>]" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$APP_DIR" ]]; then
  echo "Missing app directory: $APP_DIR" >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

mkdir -p "$MUSIC_DIR"

generate_music_track() {
  local out_file="$1"
  local freq1="$2"
  local freq2="$3"
  local noise_amp="$4"
  local duration="$5"

  if [[ -f "$out_file" ]]; then
    return 0
  fi

  ffmpeg -y \
    -f lavfi -i "sine=frequency=${freq1}:duration=${duration}" \
    -f lavfi -i "sine=frequency=${freq2}:duration=${duration}" \
    -f lavfi -i "anoisesrc=color=pink:amplitude=${noise_amp}:duration=${duration}" \
    -filter_complex "[0:a]volume=0.20[a0];[1:a]volume=0.10[a1];[2:a]lowpass=f=4200,highpass=f=110,volume=0.08[a2];[a0][a1][a2]amix=inputs=3,loudnorm=I=-20:TP=-2:LRA=9" \
    -c:a libmp3lame -b:a 160k "$out_file" >/dev/null 2>&1
}

echo "Ensuring mood-based music files..."
generate_music_track "${MUSIC_DIR}/funny_light_loop.mp3" 160 300 0.020 46
generate_music_track "${MUSIC_DIR}/upbeat_tech_loop.mp3" 180 360 0.016 46
generate_music_track "${MUSIC_DIR}/devotional_soft_loop.mp3" 120 240 0.010 46
generate_music_track "${MUSIC_DIR}/desi_dramatic_loop.mp3" 140 280 0.018 46

echo "Music files ready in: ${MUSIC_DIR}"

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo "Installing dependencies..."
if ! pip install -r "$APP_DIR/requirements.txt"; then
  echo "Primary dependency install failed (likely offline). Retrying without optional python-dotenv..."
  TMP_REQ="$(mktemp)"
  grep -v '^python-dotenv' "$APP_DIR/requirements.txt" > "$TMP_REQ"
  pip install -r "$TMP_REQ"
  rm -f "$TMP_REQ"
fi

if [[ ! -f "$APP_ENV" ]]; then
  cp "$APP_DIR/.env.example" "$APP_ENV"
fi

if [[ -f "$ROOT_ENV" ]]; then
  echo "Copying keys from root .env -> daily_shorts/.env"
  ROOT_ENV_PATH="$ROOT_ENV" APP_ENV_PATH="$APP_ENV" python3 - <<'PY'
from pathlib import Path
import os

root_env = Path(os.environ["ROOT_ENV_PATH"])
app_env = Path(os.environ["APP_ENV_PATH"])

keys = [
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "ELEVENLABS_API_KEY",
    "PIXABAY_API_KEY",
    "PEXELS_API_KEY",
    "MIN_CLIP_WIDTH",
    "MIN_CLIP_HEIGHT",
]

def parse(path: Path) -> dict:
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data

root_vals = parse(root_env)
app_vals = parse(app_env)
for key in keys:
    if root_vals.get(key):
        app_vals[key] = root_vals[key]

lines = [f"{k}={v}" for k, v in app_vals.items()]
app_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
fi

echo "Setup complete."
echo "App path: $APP_DIR"
echo "Venv: $VENV_DIR"

if [[ -n "$RUN_CHANNEL" ]]; then
  case "$RUN_CHANNEL" in
    tech|funny|bhakti|mirzapuri)
      echo "Running channel: $RUN_CHANNEL"
      (cd "$APP_DIR" && SHORTS_ENABLE_BOT_TTS="${SHORTS_ENABLE_BOT_TTS:-1}" python run_daily.py --channel "$RUN_CHANNEL")
      ;;
    *)
      echo "Invalid channel: $RUN_CHANNEL" >&2
      exit 1
      ;;
  esac
else
  echo "To run manually:"
  echo "  source .venv/bin/activate"
  echo "  cd daily_shorts"
  echo "  python run_daily.py --channel funny"
fi
