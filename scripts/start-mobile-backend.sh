#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_HOST="${COURSE_NAVIGATOR_API_HOST:-0.0.0.0}"
API_PORT="${COURSE_NAVIGATOR_API_PORT:-18000}"
SERVICE_NAME="${COURSE_NAVIGATOR_SERVICE_NAME:-Course Navigator on $(scutil --get LocalHostName 2>/dev/null || hostname -s)}"
ADVERTISE_PID=""
API_PID=""

cleanup() {
  if [[ -n "$ADVERTISE_PID" ]]; then
    kill "$ADVERTISE_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$API_PID" ]]; then
    pkill -TERM -P "$API_PID" >/dev/null 2>&1 || true
    kill "$API_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need_command uv

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Starting Course Navigator API for iPhone/iPad on http://${API_HOST}:${API_PORT}"
echo
echo "Try these device URLs from the iOS app:"
if command -v ipconfig >/dev/null 2>&1; then
  for device in en0 en1; do
    address="$(ipconfig getifaddr "$device" 2>/dev/null || true)"
    if [[ -n "$address" ]]; then
      echo "  http://${address}:${API_PORT}"
    fi
  done
fi
if command -v dns-sd >/dev/null 2>&1; then
  dns-sd -R "$SERVICE_NAME" _coursenav._tcp local "$API_PORT" path=/api >/dev/null 2>&1 &
  ADVERTISE_PID="$!"
  echo
  echo "Bonjour discovery: $SERVICE_NAME (_coursenav._tcp)"
fi
echo
echo "Keep this terminal open while using the iOS app."
echo

uv run uvicorn course_navigator.app:app --app-dir backend --host "$API_HOST" --port "$API_PORT" &
API_PID="$!"
wait "$API_PID"
