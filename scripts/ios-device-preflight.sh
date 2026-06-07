#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DERIVED_DATA_DIR="${COURSE_NAVIGATOR_IOS_DERIVED_DATA:-/Volumes/Acer SSD N5000/CodexBuilds/XcodeDerivedData}"
PROJECT_PATH="ios/CourseNavigatorMobile.xcodeproj"
API_HOST="${COURSE_NAVIGATOR_API_HOST:-0.0.0.0}"
API_PORT="${COURSE_NAVIGATOR_API_PORT:-18000}"

section() {
  printf '\n== %s ==\n' "$1"
}

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

section "Disk"
df -h / || true
if [[ -d /Volumes/Acer\ SSD\ N5000 ]]; then
  df -h /Volumes/Acer\ SSD\ N5000 || true
  mkdir -p "$DERIVED_DATA_DIR"
  printf 'Recommended Xcode Derived Data: %s\n' "$DERIVED_DATA_DIR"
else
  printf 'External SSD /Volumes/Acer SSD N5000 is not mounted.\n'
fi

section "Xcode"
if [[ -d /Applications/Xcode.app ]]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
if command -v xcodebuild >/dev/null 2>&1; then
  xcodebuild -version
  xcodebuild -showsdks | grep -E 'iphoneos|iphonesimulator' || true
else
  printf 'xcodebuild was not found. Open Xcode once after installation.\n'
fi

section "Project"
if [[ -d "$PROJECT_PATH" ]]; then
  printf 'Project exists: %s\n' "$PROJECT_PATH"
else
  printf 'Missing project: %s\n' "$PROJECT_PATH"
fi

section "Backend"
printf 'Start backend for devices with:\n  bash scripts/start-mobile-backend.sh\n'
if is_loopback_host "$API_HOST"; then
  printf 'Warning: COURSE_NAVIGATOR_API_HOST=%s only listens on this Mac; iPhone/iPad needs 0.0.0.0 or a LAN address.\n' "$API_HOST"
else
  printf 'Mobile backend bind host: %s\n' "$API_HOST"
fi
printf 'Likely device URLs:\n'
print_lan_urls || printf '  No LAN IPv4 address was detected. Check Wi-Fi/Ethernet before using the iOS app.\n'
if command -v curl >/dev/null 2>&1 && curl -fsS "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1; then
  printf 'Local backend is already responding on 127.0.0.1:%s.\n' "$API_PORT"
else
  printf 'Local backend is not responding on 127.0.0.1:%s yet.\n' "$API_PORT"
fi

section "Devices"
if command -v xcrun >/dev/null 2>&1; then
  xcrun devicectl list devices || true
else
  printf 'xcrun was not found.\n'
fi

section "Next"
printf '1. Connect iPhone/iPad, unlock it, and trust this Mac.\n'
printf '2. Enable Developer Mode on the device if iOS asks for it.\n'
printf '3. In Xcode Settings > Locations, set Derived Data to the external SSD path above.\n'
printf '4. Run bash scripts/ios-install-device.sh, or open %s, choose Personal Team, then Run on the connected device.\n' "$PROJECT_PATH"
