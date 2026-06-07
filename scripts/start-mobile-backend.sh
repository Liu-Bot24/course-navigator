#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_HOST="${COURSE_NAVIGATOR_API_HOST:-0.0.0.0}"
API_PORT="${COURSE_NAVIGATOR_API_PORT:-18000}"
SERVICE_NAME="${COURSE_NAVIGATOR_SERVICE_NAME:-Course Navigator on $(scutil --get LocalHostName 2>/dev/null || hostname -s)}"
ADVERTISE_PID=""
API_PID=""

is_loopback_host() {
  case "$1" in
    127.*|localhost|::1|\[::1\])
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_unusable_device_url_address() {
  case "$1" in
    169.254.*)
      return 0
      ;;
    *)
      is_loopback_host "$1"
      ;;
  esac
}

print_lan_urls() {
  local printed_addresses=""
  local device address

  if ! command -v ipconfig >/dev/null 2>&1 || ! command -v ifconfig >/dev/null 2>&1; then
    return
  fi

  for device in $(ifconfig -l); do
    case "$device" in
      lo*|utun*|awdl*|llw*|bridge*|anpi*|ap*)
        continue
        ;;
    esac

    address="$(ipconfig getifaddr "$device" 2>/dev/null || true)"
    if [[ -z "$address" ]] || is_unusable_device_url_address "$address"; then
      continue
    fi
    if [[ " $printed_addresses " == *" $address "* ]]; then
      continue
    fi

    printf '  http://%s:%s (%s)\n' "$address" "$API_PORT" "$device"
    printed_addresses="$printed_addresses $address"
  done

  [[ -n "$printed_addresses" ]]
}

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

if is_loopback_host "$API_HOST"; then
  printf 'COURSE_NAVIGATOR_API_HOST=%s only listens on this Mac.\n' "$API_HOST" >&2
  printf 'Use COURSE_NAVIGATOR_API_HOST=0.0.0.0 for iPhone/iPad access, then run this script again.\n' >&2
  exit 1
fi

need_command uv

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Starting Course Navigator API for iPhone/iPad on http://${API_HOST}:${API_PORT}"
echo
echo "Try these device URLs from the iOS app:"
print_lan_urls || printf '  No LAN IPv4 address was detected. Check Wi-Fi/Ethernet, then run scripts/ios-device-preflight.sh.\n'
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
