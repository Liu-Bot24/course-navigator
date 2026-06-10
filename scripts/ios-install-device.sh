#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEFAULT_DERIVED_DATA_DIR="$ROOT_DIR/ios/.build/xcode-derived-data/device-install"
CUSTOM_DERIVED_DATA_DIR="${COURSE_NAVIGATOR_IOS_DERIVED_DATA:-}"
DERIVED_DATA_DIR="${CUSTOM_DERIVED_DATA_DIR:-$DEFAULT_DERIVED_DATA_DIR}"
MIN_DERIVED_DATA_FREE_GIB="${COURSE_NAVIGATOR_IOS_MIN_DERIVED_DATA_FREE_GIB:-8}"
PROJECT_PATH="ios/CourseNavigatorMobile.xcodeproj"
SCHEME="CourseNavigatorMobile"
CONFIGURATION="${COURSE_NAVIGATOR_IOS_CONFIGURATION:-Debug}"
DEFAULT_BUNDLE_ID="com.example.coursenavigator.mobile"
BUNDLE_ID="${COURSE_NAVIGATOR_IOS_BUNDLE_ID:-$DEFAULT_BUNDLE_ID}"
APP_NAME="${COURSE_NAVIGATOR_IOS_APP_NAME:-Course Navigator}"
DEVICE_ID="${COURSE_NAVIGATOR_IOS_DEVICE_ID:-}"
TEAM_ID="${COURSE_NAVIGATOR_IOS_TEAM_ID:-}"
LAUNCH_AFTER_INSTALL="${COURSE_NAVIGATOR_IOS_LAUNCH_AFTER_INSTALL:-1}"
INSTALL_ALL="${COURSE_NAVIGATOR_IOS_INSTALL_ALL:-0}"
DEVICE_IDS=()
DEVICE_NAMES=()

section() {
  printf '\n== %s ==\n' "$1"
}

display_path() {
  local path="$1"
  if [[ "$path" == "$ROOT_DIR/"* ]]; then
    printf '%s' "${path#$ROOT_DIR/}"
  else
    printf 'custom path'
  fi
}

check_derived_data_location() {
  if [[ -z "$CUSTOM_DERIVED_DATA_DIR" ]]; then
    return
  fi

  local parent_dir
  parent_dir="$(dirname "$DERIVED_DATA_DIR")"
  if [[ ! -d "$parent_dir" ]]; then
    printf 'DerivedData override parent directory does not exist.\n' >&2
    printf 'No build was started. Set COURSE_NAVIGATOR_IOS_DERIVED_DATA to another path or clear it to use the project build cache.\n' >&2
    exit 1
  fi
}

check_derived_data_disk() {
  local min_free_gib="$MIN_DERIVED_DATA_FREE_GIB"
  if [[ -z "$min_free_gib" || "$min_free_gib" == *[!0-9]* ]]; then
    min_free_gib=8
  fi

  mkdir -p "$DERIVED_DATA_DIR"

  local available_gib
  available_gib="$(df -g "$DERIVED_DATA_DIR" | awk 'NR == 2 {print $4}')"
  if [[ -n "$available_gib" && "$available_gib" -lt "$min_free_gib" ]]; then
    printf 'DerivedData location has only %s GiB free.\n' "$available_gib" >&2
    printf 'No build was started. Free space or set COURSE_NAVIGATOR_IOS_DERIVED_DATA to another path.\n' >&2
    exit 1
  fi
}

check_local_disk() {
  local available_gib
  available_gib="$(df -g / | awk 'NR == 2 {print $4}')"
  if [[ -n "$available_gib" && "$available_gib" -lt 8 ]]; then
    printf 'Local disk has only %s GiB free. No build was started.\n' "$available_gib" >&2
    printf 'Free local disk space before retrying.\n' >&2
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
  if ! xcodebuild -checkFirstLaunchStatus >/dev/null 2>&1; then
    printf 'Xcode first launch tasks are not complete. No build was started.\n' >&2
    printf 'Open Xcode once, sign in if needed, accept the license, then run this script again.\n' >&2
    exit 1
  fi
  if [[ ! -d "$PROJECT_PATH" ]]; then
    printf 'Missing Xcode project: %s\n' "$PROJECT_PATH" >&2
    exit 1
  fi
}

device_identifier_at() {
  local devices_json="$1"
  local index="$2"
  local id
  id="$(plutil -extract "result.devices.$index.identifier" raw -o - "$devices_json" 2>/dev/null || true)"
  if [[ -z "$id" ]]; then
    id="$(plutil -extract "result.devices.$index.hardwareProperties.udid" raw -o - "$devices_json" 2>/dev/null || true)"
  fi
  printf '%s' "$id"
}

device_name_at() {
  local devices_json="$1"
  local index="$2"
  plutil -extract "result.devices.$index.name" raw -o - "$devices_json" 2>/dev/null || true
}

detect_devices() {
  if [[ "$DEVICE_ID" == "all" ]]; then
    INSTALL_ALL=1
    DEVICE_ID=""
  fi

  if [[ -n "$DEVICE_ID" ]]; then
    printf 'Using device from COURSE_NAVIGATOR_IOS_DEVICE_ID: %s\n' "$DEVICE_ID"
    DEVICE_IDS=("$DEVICE_ID")
    DEVICE_NAMES=("explicit device")
    return
  fi

  local devices_json index current_id current_name
  devices_json="$(mktemp "${TMPDIR:-/tmp}/coursenav-ios-devices.XXXXXX")"

  if ! xcrun devicectl list devices --timeout 10 --json-output "$devices_json" >/dev/null; then
    rm -f "$devices_json"
    exit 1
  fi
  for index in $(seq 0 99); do
    current_id="$(device_identifier_at "$devices_json" "$index")"
    if [[ -z "$current_id" ]]; then
      break
    fi
    current_name="$(device_name_at "$devices_json" "$index")"
    DEVICE_IDS+=("$current_id")
    DEVICE_NAMES+=("${current_name:-$current_id}")
  done

  if [[ "${#DEVICE_IDS[@]}" -eq 0 ]]; then
    printf 'No connected iPhone/iPad was detected. No build was started.\n' >&2
    printf 'Connect the device, unlock it, trust this Mac, then run this script again.\n' >&2
    printf '\nCurrent devicectl device list:\n' >&2
    xcrun devicectl list devices || true
    rm -f "$devices_json"
    exit 1
  fi

  if [[ "${#DEVICE_IDS[@]}" -gt 1 && "$INSTALL_ALL" != "1" ]]; then
    printf 'Multiple iPhone/iPad devices were detected. No build was started.\n' >&2
    printf 'Set COURSE_NAVIGATOR_IOS_DEVICE_ID to one device ID, or set COURSE_NAVIGATOR_IOS_INSTALL_ALL=1 to install on all listed devices.\n' >&2
    printf '\nDetected devices:\n' >&2
    for index in "${!DEVICE_IDS[@]}"; do
      printf '  %s  %s\n' "${DEVICE_IDS[$index]}" "${DEVICE_NAMES[$index]}" >&2
    done
    rm -f "$devices_json"
    exit 1
  fi

  rm -f "$devices_json"
  if [[ "$INSTALL_ALL" == "1" && "${#DEVICE_IDS[@]}" -gt 1 ]]; then
    printf 'Selected all connected devices:\n'
    for index in "${!DEVICE_IDS[@]}"; do
      printf '  %s (%s)\n' "${DEVICE_NAMES[$index]}" "${DEVICE_IDS[$index]}"
    done
  else
    printf 'Selected device: %s (%s)\n' "${DEVICE_NAMES[0]}" "${DEVICE_IDS[0]}"
  fi
}

build_for_device() {
  local device_id="$1"
  local device_name="$2"
  mkdir -p "$DERIVED_DATA_DIR"
  section "Build: $device_name"
  printf 'DerivedData: %s\n' "$(display_path "$DERIVED_DATA_DIR")"

  local build_args=(
    -project "$PROJECT_PATH"
    -scheme "$SCHEME"
    -configuration "$CONFIGURATION"
    -destination "platform=iOS,id=$device_id"
    -derivedDataPath "$DERIVED_DATA_DIR"
    -allowProvisioningUpdates
    -allowProvisioningDeviceRegistration
    CODE_SIGN_STYLE=Automatic
  )

  if [[ -n "$TEAM_ID" ]]; then
    build_args+=(DEVELOPMENT_TEAM="$TEAM_ID")
  fi
  if [[ -n "$BUNDLE_ID" ]]; then
    build_args+=(PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID")
  fi

  if ! xcodebuild "${build_args[@]}" build; then
    print_build_failure_help
    exit 1
  fi
}

print_build_failure_help() {
  section "Build failed"
  cat >&2 <<'EOF'
If this failed during signing or provisioning, check these first:
  1. Open Xcode once and sign in with your Apple Account.
  2. Open ios/CourseNavigatorMobile.xcodeproj and select your Personal Team in Signing & Capabilities.
  3. If the bundle identifier is already taken, rerun with COURSE_NAVIGATOR_IOS_BUNDLE_ID=com.yourname.coursenavigator.mobile.
  4. If Xcode shows a Team ID, rerun with COURSE_NAVIGATOR_IOS_TEAM_ID=<TeamID>.
  5. Keep the iPhone/iPad unlocked, trusted, and in Developer Mode before retrying.
EOF
}

install_app() {
  local device_id="$1"
  local device_name="$2"
  local app_path
  app_path="$(find_built_app_path)" || exit 1

  section "Install: $device_name"
  xcrun devicectl device install app --device "$device_id" "$app_path"

  if [[ "$LAUNCH_AFTER_INSTALL" == "1" ]]; then
    section "Launch: $device_name"
    xcrun devicectl device process launch --terminate-existing --device "$device_id" "$BUNDLE_ID" || true
  fi
}

find_built_app_path() {
  local build_products_dir="$DERIVED_DATA_DIR/Build/Products/$CONFIGURATION-iphoneos"
  local expected_app_path="$build_products_dir/$APP_NAME.app"
  if [[ -d "$expected_app_path" ]]; then
    printf '%s\n' "$expected_app_path"
    return 0
  fi

  local candidates=()
  local candidate
  while IFS= read -r -d '' candidate; do
    candidates+=("$candidate")
  done < <(find "$build_products_dir" -maxdepth 1 -type d -name '*.app' -print0 2>/dev/null)

  if [[ "${#candidates[@]}" -eq 1 ]]; then
    printf '%s\n' "${candidates[0]}"
    return 0
  fi

  printf 'Built app was not found: %s\n' "$expected_app_path" >&2
  if [[ "${#candidates[@]}" -gt 1 ]]; then
    printf 'Multiple built apps were found; set COURSE_NAVIGATOR_IOS_APP_NAME to the product name to install.\n' >&2
    for candidate in "${candidates[@]}"; do
      printf '  %s\n' "$candidate" >&2
    done
  elif [[ -d "$build_products_dir" ]]; then
    printf 'Build products directory exists but contains no .app bundle: %s\n' "$build_products_dir" >&2
  else
    printf 'Build products directory does not exist: %s\n' "$build_products_dir" >&2
  fi
  return 1
}

section "Build Cache"
check_derived_data_location
check_local_disk
check_derived_data_disk
prepare_xcode

section "Xcode"
xcodebuild -version

section "Device"
detect_devices

for index in "${!DEVICE_IDS[@]}"; do
  build_for_device "${DEVICE_IDS[$index]}" "${DEVICE_NAMES[$index]}"
  install_app "${DEVICE_IDS[$index]}" "${DEVICE_NAMES[$index]}"
done

section "Done"
if [[ "${#DEVICE_IDS[@]}" -gt 1 ]]; then
  printf 'Course Navigator was built and installed on %s devices.\n' "${#DEVICE_IDS[@]}"
else
  printf 'Course Navigator was built and installed on the selected device.\n'
fi
