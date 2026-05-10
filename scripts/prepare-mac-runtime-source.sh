#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCE_DIR="$ROOT_DIR/launcher/src-tauri/resources/runtime-source"
MANIFEST="$RESOURCE_DIR/.course-navigator-runtime.json"

rm -rf "$RESOURCE_DIR"
mkdir -p "$RESOURCE_DIR"

rsync -a "$ROOT_DIR/" "$RESOURCE_DIR/" \
  --filter '+ .env.example' \
  --filter '- .env' \
  --filter '- .env.*' \
  --exclude '.course-navigator-deps.json' \
  --exclude '.git/' \
  --exclude '.gitignore' \
  --exclude '.DS_Store' \
  --exclude '.venv/' \
  --exclude 'node_modules/' \
  --exclude 'dist/' \
  --exclude 'Casks/' \
  --exclude 'frontend/dist/' \
  --exclude 'backend/tests/' \
  --exclude 'frontend/src/*.test.*' \
  --exclude '*.tsbuildinfo' \
  --exclude 'launcher/' \
  --exclude '.worktrees/' \
  --exclude '.course-navigator/' \
  --exclude 'course-navigator-workspace/' \
  --exclude 'data/' \
  --exclude 'downloads/' \
  --exclude 'backend/**/__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.mypy_cache/' \
  --exclude 'scripts/build-mac-dmg.sh' \
  --exclude 'scripts/prepare-mac-runtime-source.sh' \
  --exclude 'docs/superpowers/'

touch "$RESOURCE_DIR/.gitkeep"

SOURCE_HASH="$(
  cd "$RESOURCE_DIR"
  find . -type f ! -name '.course-navigator-runtime.json' -print0 \
    | sort -z \
    | xargs -0 shasum -a 256 \
    | shasum -a 256 \
    | awk '{print $1}'
)"

cat > "$MANIFEST" <<JSON
{
  "name": "course-navigator-runtime-source",
  "sourceHash": "$SOURCE_HASH"
}
JSON

echo "Prepared macOS runtime source at $RESOURCE_DIR"
