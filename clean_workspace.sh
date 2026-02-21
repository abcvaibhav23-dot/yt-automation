#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="runtime"
DRY_RUN="0"

usage() {
  cat <<'EOF'
Usage:
  ./clean_workspace.sh [--runtime|--all] [--dry-run]

Options:
  --runtime   Clean generated/runtime artifacts only (default)
  --all       Runtime clean + extra temp files (safe for source code)
  --dry-run   Show what would be removed without deleting
  -h, --help  Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime)
      MODE="runtime"
      shift
      ;;
    --all)
      MODE="all"
      shift
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

remove_file() {
  local p="$1"
  if [[ -f "$p" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "[dry-run] rm $p"
    else
      rm -f "$p"
      echo "removed $p"
    fi
  fi
}

remove_dir_contents() {
  local d="$1"
  if [[ -d "$d" ]]; then
    while IFS= read -r -d '' f; do
      remove_file "$f"
    done < <(find "$d" -type f ! -name ".gitkeep" -print0)
  fi
}

echo "Cleaning mode: $MODE (dry-run=$DRY_RUN)"

# Root junk files
while IFS= read -r -d '' f; do remove_file "$f"; done < <(find "$ROOT_DIR" -name ".DS_Store" -type f -print0)
while IFS= read -r -d '' f; do remove_file "$f"; done < <(find "$ROOT_DIR" -name "*.tmp" -type f -print0)
while IFS= read -r -d '' f; do remove_file "$f"; done < <(find "$ROOT_DIR" -name "*.temp" -type f -print0)

# daily_shorts runtime artifacts
remove_dir_contents "$ROOT_DIR/daily_shorts/output"
remove_dir_contents "$ROOT_DIR/daily_shorts/logs"
remove_dir_contents "$ROOT_DIR/daily_shorts/final"
remove_dir_contents "$ROOT_DIR/daily_shorts/assets/cache"

# shorts_factory runtime artifacts
remove_dir_contents "$ROOT_DIR/shorts_factory/output"
remove_dir_contents "$ROOT_DIR/shorts_factory/logs"
remove_dir_contents "$ROOT_DIR/shorts_factory/audio"

if [[ "$MODE" == "all" ]]; then
  # Extra generated text/artifacts (safe)
  remove_file "$ROOT_DIR/shorts_factory/video_export_plan.txt"
  while IFS= read -r -d '' d; do
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "[dry-run] rm -rf $d"
    else
      rm -rf "$d"
      echo "removed $d"
    fi
  done < <(find "$ROOT_DIR" -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" \) -print0)
fi

# Remove empty dirs under final/cache/output if any
for d in "$ROOT_DIR/daily_shorts/final" "$ROOT_DIR/daily_shorts/assets/cache" "$ROOT_DIR/daily_shorts/output" "$ROOT_DIR/shorts_factory/output" "$ROOT_DIR/shorts_factory/logs" "$ROOT_DIR/shorts_factory/audio"; do
  if [[ -d "$d" ]]; then
    find "$d" -type d -empty -delete || true
  fi
done

echo "Cleanup completed."
