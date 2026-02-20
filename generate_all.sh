#!/usr/bin/env bash
set -euo pipefail

# One-command batch generation for 4 short types.
# Usage:
#   ./generate_all.sh
#   ./generate_all.sh sonbhadra
#   ./generate_all.sh bihar en hi

REGION="${1:-bihar}"
EN_VOICE_LANG="${2:-en}"
HI_VOICE_LANG="${3:-hi}"
PYTHON_BIN=".venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: $PYTHON_BIN not found. Create venv and install dependencies first." >&2
  exit 1
fi

COMMON_FLAGS=(--ai-visuals --no-srt)

# First run performs fresh cleanup (default behavior).
"$PYTHON_BIN" -m shorts_factory.src.main \
  --channel "Tech Daily" \
  --style tech \
  --voice-lang "$EN_VOICE_LANG" \
  "${COMMON_FLAGS[@]}"

# Remaining runs keep history so all videos remain in output.
"$PYTHON_BIN" -m shorts_factory.src.main \
  --channel "Comedy Burst" \
  --style funny \
  --voice-lang "$EN_VOICE_LANG" \
  --keep-history \
  "${COMMON_FLAGS[@]}"

"$PYTHON_BIN" -m shorts_factory.src.main \
  --channel "Bhakti Vibes" \
  --style bhakti \
  --voice-lang "$HI_VOICE_LANG" \
  --keep-history \
  "${COMMON_FLAGS[@]}"

"$PYTHON_BIN" -m shorts_factory.src.main \
  --channel "UP-Bihar Shorts" \
  --style regional \
  --region "$REGION" \
  --voice-lang "$HI_VOICE_LANG" \
  --keep-history \
  "${COMMON_FLAGS[@]}"

echo "Done: generated tech, funny, bhakti, regional ($REGION)."
