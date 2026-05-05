#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_HOST="${COURSE_NAVIGATOR_API_HOST:-127.0.0.1}"
API_PORT="${COURSE_NAVIGATOR_API_PORT:-8000}"
WEB_HOST="${COURSE_NAVIGATOR_WEB_HOST:-127.0.0.1}"
WEB_PORT="${COURSE_NAVIGATOR_WEB_PORT:-5173}"

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    echo "Install it, then run this script again." >&2
    exit 1
  fi
}

warn_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Warning: $1 was not found." >&2
    echo "Course Navigator will still start, but local video cache, audio extraction, and media conversion may fail until $1 is installed." >&2
  fi
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempts=60
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "$label did not become ready at $url" >&2
  return 1
}

cleanup() {
  if [[ -n "${API_PID:-}" ]]; then
    kill "$API_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${WEB_PID:-}" ]]; then
    kill "$WEB_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

need_command node
need_command npm
need_command uv
need_command curl
warn_command ffmpeg

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Installing Python dependencies..."
uv sync

echo "Checking yt-dlp..."
uv run yt-dlp --version >/dev/null

echo "Installing web dependencies..."
if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi

echo "Starting Course Navigator API on http://${API_HOST}:${API_PORT}"
uv run uvicorn course_navigator.app:app --app-dir backend --host "$API_HOST" --port "$API_PORT" &
API_PID=$!
wait_for_url "http://${API_HOST}:${API_PORT}/api/items" "API"

echo "Starting Course Navigator web app on http://${WEB_HOST}:${WEB_PORT}"
npm run dev -- --host "$WEB_HOST" --port "$WEB_PORT" &
WEB_PID=$!
wait_for_url "http://${WEB_HOST}:${WEB_PORT}" "Web app"

echo
echo "Course Navigator is ready:"
echo "  http://${WEB_HOST}:${WEB_PORT}"
echo
echo "Press Ctrl+C to stop both services."

while kill -0 "$API_PID" >/dev/null 2>&1 && kill -0 "$WEB_PID" >/dev/null 2>&1; do
  sleep 1
done
