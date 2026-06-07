#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

EXTERNAL_SSD="/Volumes/Acer SSD N5000"
DEFAULT_DERIVED_DATA_DIR="$EXTERNAL_SSD/CodexBuilds/course-navigator-ios-device-install"
DERIVED_DATA_DIR="${COURSE_NAVIGATOR_IOS_DERIVED_DATA:-$DEFAULT_DERIVED_DATA_DIR}"
PROJECT_PATH="ios/CourseNavigatorMobile.xcodeproj"
SCHEME="CourseNavigatorMobile"
CONFIGURATION="${COURSE_NAVIGATOR_IOS_CONFIGURATION:-Debug}"
DEFAULT_BUNDLE_ID="com.liuqi.coursenavigator.mobile"
BUNDLE_ID="${COURSE_NAVIGATOR_IOS_BUNDLE_ID:-$DEFAULT_BUNDLE_ID}"
APP_NAME="${COURSE_NAVIGATOR_IOS_APP_NAME:-Course Navigator}"
DEVICE_ID="${COURSE_NAVIGATOR_IOS_DEVICE_ID:-}"
TEAM_ID="${COURSE_NAVIGATOR_IOS_TEAM_ID:-}"
LAUNCH_AFTER_INSTALL="${COURSE_NAVIGATOR_IOS_LAUNCH_AFTER_INSTALL:-1}"

section() {
  printf '\n== %s ==\n' "$1"
}

require_external_derived_data() {
  if [[ "$DERIVED_DATA_DIR" == "$EXTERNAL_SSD/"* && ! -d "$EXTERNAL_SSD" ]]; then
    printf 'External SSD is not mounted: %s\n' "$EXTERNAL_SSD" >&2
    printf 'No build was started. Mount the SSD or set COURSE_NAVIGATOR_IOS_DERIVED_DATA to another safe path.\n' >&2
    exit 1
  fi
}

check_local_disk() {
  local available_gib
  available_gib="$(df -g / | awk 'NR == 2 {print $4}')"
  if [[ -n "$available_gib" && "$available_gib" -lt 8 ]]; then
    printf 'Local disk has only %s GiB free. No build was started.\n' "$available_gib" >&2
    printf 'Free local disk space first, even though DerivedData is on the external SSD.\n' >&2
    exit 1
  fi
}

prepare_xcode() {
  if [[ -d /Applications/Xcode.app ]]; then
    export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
  fi
  if ! command -v xcodebuild >/dev/null 2>&1 || ! command -v xcrun >/dev/null 2>&1; then
    printf 'Xcode command line tools were not found. Open Xcode once after installation.\n' >&2
    exit 1
  fi
  if [[ ! -d "$PROJECT_PATH" ]]; then
    printf 'Missing Xcode project: %s\n' "$PROJECT_PATH" >&2
    exit 1
  fi
}

detect_device() {
  if [[ -n "$DEVICE_ID" ]]; then
    printf 'Using device from COURSE_NAVIGATOR_IOS_DEVICE_ID: %s\n' "$DEVICE_ID"
    return
  fi

  local devices_json
  devices_json="$(mktemp "${TMPDIR:-/tmp}/coursenav-ios-devices.XXXXXX.json")"

  xcrun devicectl list devices --timeout 10 --json-output "$devices_json" >/dev/null
  DEVICE_ID="$(
    plutil -extract result.devices.0.identifier raw -o - "$devices_json" 2>/dev/null \
      || plutil -extract result.devices.0.hardwareProperties.udid raw -o - "$devices_json" 2>/dev/null \
      || true
  )"

  if [[ -z "$DEVICE_ID" ]]; then
    printf 'No connected iPhone/iPad was detected. No build was started.\n' >&2
    printf 'Connect the device, unlock it, trust this Mac, then run this script again.\n' >&2
    printf '\nCurrent devicectl device list:\n' >&2
    xcrun devicectl list devices || true
    rm -f "$devices_json"
    exit 1
  fi

  local device_name
  device_name="$(plutil -extract result.devices.0.name raw -o - "$devices_json" 2>/dev/null || true)"
  rm -f "$devices_json"
  if [[ -n "$device_name" ]]; then
    printf 'Selected device: %s (%s)\n' "$device_name" "$DEVICE_ID"
  else
    printf 'Selected device: %s\n' "$DEVICE_ID"
  fi
}

build_for_device() {
  mkdir -p "$DERIVED_DATA_DIR"
  section "Build"
  printf 'DerivedData: %s\n' "$DERIVED_DATA_DIR"

  local build_args=(
    -project "$PROJECT_PATH"
    -scheme "$SCHEME"
    -configuration "$CONFIGURATION"
    -destination "platform=iOS,id=$DEVICE_ID"
    -derivedDataPath "$DERIVED_DATA_DIR"
    -allowProvisioningUpdates
    CODE_SIGN_STYLE=Automatic
  )

  if [[ -n "$TEAM_ID" ]]; then
    build_args+=(DEVELOPMENT_TEAM="$TEAM_ID")
  fi
  if [[ -n "$BUNDLE_ID" ]]; then
    build_args+=(PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID")
  fi

  xcodebuild "${build_args[@]}" build
}

install_app() {
  local app_path="$DERIVED_DATA_DIR/Build/Products/$CONFIGURATION-iphoneos/$APP_NAME.app"
  if [[ ! -d "$app_path" ]]; then
    printf 'Built app was not found: %s\n' "$app_path" >&2
    exit 1
  fi

  section "Install"
  xcrun devicectl device install app --device "$DEVICE_ID" "$app_path"

  if [[ "$LAUNCH_AFTER_INSTALL" == "1" ]]; then
    section "Launch"
    xcrun devicectl device process launch --terminate-existing --device "$DEVICE_ID" "$BUNDLE_ID" || true
  fi
}

section "Disk"
df -h / || true
if [[ -d "$EXTERNAL_SSD" ]]; then
  df -h "$EXTERNAL_SSD" || true
fi

require_external_derived_data
check_local_disk
prepare_xcode

section "Xcode"
xcodebuild -version

section "Device"
detect_device

build_for_device
install_app

section "Done"
printf 'Course Navigator was built and installed on the selected device.\n'
