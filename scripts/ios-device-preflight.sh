#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

EXTERNAL_SSD="/Volumes/Acer SSD N5000"
DEFAULT_DERIVED_DATA_DIR="$EXTERNAL_SSD/CodexBuilds/XcodeDerivedData"
DERIVED_DATA_DIR="${COURSE_NAVIGATOR_IOS_DERIVED_DATA:-$DEFAULT_DERIVED_DATA_DIR}"
ALLOW_LOCAL_DERIVED_DATA="${COURSE_NAVIGATOR_ALLOW_LOCAL_DERIVED_DATA:-0}"
MIN_DERIVED_DATA_FREE_GIB="${COURSE_NAVIGATOR_IOS_MIN_DERIVED_DATA_FREE_GIB:-8}"
PROJECT_PATH="ios/CourseNavigatorMobile.xcodeproj"
SCHEME="CourseNavigatorMobile"
CONFIGURATION="${COURSE_NAVIGATOR_IOS_CONFIGURATION:-Debug}"
INFO_PLIST_PATH="ios/CourseNavigatorMobile/Info.plist"
API_HOST="${COURSE_NAVIGATOR_API_HOST:-0.0.0.0}"
API_PORT="${COURSE_NAVIGATOR_API_PORT:-18000}"
DERIVED_DATA_READY=0

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

volume_root_for_path() {
  local path="$1"
  local relative_volume_path volume_name
  relative_volume_path="${path#/Volumes/}"
  volume_name="${relative_volume_path%%/*}"
  if [[ -n "$volume_name" && "$path" == /Volumes/* ]]; then
    printf '/Volumes/%s' "$volume_name"
  fi
}

is_mounted_volume_root() {
  local volume_root="$1"
  [[ -n "$volume_root" ]] && mount | grep -F " on $volume_root (" >/dev/null 2>&1
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

check_derived_data_path() {
  local min_free_gib="$MIN_DERIVED_DATA_FREE_GIB"
  if [[ -z "$min_free_gib" || "$min_free_gib" == *[!0-9]* ]]; then
    min_free_gib=8
  fi

  if [[ "$DERIVED_DATA_DIR" != /Volumes/* && "$ALLOW_LOCAL_DERIVED_DATA" != "1" ]]; then
    printf 'Recommended Xcode Derived Data is not on an external volume: %s\n' "$DERIVED_DATA_DIR"
    printf 'Set COURSE_NAVIGATOR_IOS_DERIVED_DATA to the external SSD path, or set COURSE_NAVIGATOR_ALLOW_LOCAL_DERIVED_DATA=1 intentionally.\n'
    return
  fi

  if [[ "$DERIVED_DATA_DIR" == /Volumes/* ]]; then
    local volume_root
    volume_root="$(volume_root_for_path "$DERIVED_DATA_DIR")"
    if ! is_mounted_volume_root "$volume_root"; then
      printf 'Recommended Xcode Derived Data volume is not mounted: %s\n' "$volume_root"
      printf 'Project build settings will be skipped to avoid creating a local /Volumes cache path.\n'
      return
    fi
  fi

  mkdir -p "$DERIVED_DATA_DIR"

  local available_gib
  available_gib="$(df -g "$DERIVED_DATA_DIR" | awk 'NR == 2 {print $4}')"
  if [[ -n "$available_gib" && "$available_gib" -lt "$min_free_gib" ]]; then
    printf 'Recommended Xcode Derived Data volume has only %s GiB free: %s\n' "$available_gib" "$DERIVED_DATA_DIR"
    return
  fi

  DERIVED_DATA_READY=1
  printf 'Recommended Xcode Derived Data: %s\n' "$DERIVED_DATA_DIR"
}

print_xcode_derived_data_preference() {
  local style custom_location
  style="$(defaults read com.apple.dt.Xcode IDEDerivedDataLocationStyle 2>/dev/null || true)"
  custom_location="$(defaults read com.apple.dt.Xcode IDECustomDerivedDataLocation 2>/dev/null || true)"

  if [[ -z "$style" && -z "$custom_location" ]]; then
    printf 'Xcode Derived Data preference: not customized\n'
    return
  fi

  if [[ -n "$custom_location" ]]; then
    printf 'Xcode Derived Data preference: %s (%s)\n' "${style:-unknown}" "$custom_location"
    if [[ "$custom_location" != /Volumes/* ]]; then
      printf 'Warning: Xcode custom Derived Data is not on an external volume.\n'
    fi
  else
    printf 'Xcode Derived Data preference: %s\n' "$style"
  fi
}

plist_raw() {
  plutil -extract "$1" raw -o - "$INFO_PLIST_PATH" 2>/dev/null || true
}

print_project_config() {
  section "Project"
  if [[ ! -d "$PROJECT_PATH" ]]; then
    printf 'Missing project: %s\n' "$PROJECT_PATH"
    return
  fi
  printf 'Project exists: %s\n' "$PROJECT_PATH"

  if ! command -v xcodebuild >/dev/null 2>&1; then
    printf 'Build settings: unavailable because xcodebuild was not found.\n'
    return
  fi
  if [[ "$DERIVED_DATA_READY" != "1" ]]; then
    printf 'Build settings: skipped because the Derived Data path is not ready.\n'
    return
  fi

  local build_settings
  build_settings="$(mktemp "${TMPDIR:-/tmp}/coursenav-ios-build-settings.XXXXXX")"
  if xcodebuild \
    -project "$PROJECT_PATH" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -destination 'generic/platform=iOS' \
    -derivedDataPath "$DERIVED_DATA_DIR" \
    -showBuildSettings >"$build_settings" 2>/dev/null; then
    local bundle_id product_name device_family deployment_target app_icon_name development_team code_sign_identity platform_name
    bundle_id="$(awk -F ' = ' '/^[[:space:]]*PRODUCT_BUNDLE_IDENTIFIER = / {print $2; exit}' "$build_settings")"
    product_name="$(awk -F ' = ' '/^[[:space:]]*PRODUCT_NAME = / {print $2; exit}' "$build_settings")"
    device_family="$(awk -F ' = ' '/^[[:space:]]*TARGETED_DEVICE_FAMILY = / {print $2; exit}' "$build_settings")"
    deployment_target="$(awk -F ' = ' '/^[[:space:]]*IPHONEOS_DEPLOYMENT_TARGET = / {print $2; exit}' "$build_settings")"
    app_icon_name="$(awk -F ' = ' '/^[[:space:]]*ASSETCATALOG_COMPILER_APPICON_NAME = / {print $2; exit}' "$build_settings")"
    development_team="$(awk -F ' = ' '/^[[:space:]]*DEVELOPMENT_TEAM = / {print $2; exit}' "$build_settings")"
    code_sign_identity="$(awk -F ' = ' '/^[[:space:]]*CODE_SIGN_IDENTITY = / {print $2; exit}' "$build_settings")"
    platform_name="$(awk -F ' = ' '/^[[:space:]]*PLATFORM_NAME = / {print $2; exit}' "$build_settings")"

    printf 'Product name: %s\n' "${product_name:-unknown}"
    printf 'Bundle identifier: %s\n' "${bundle_id:-unknown}"
    printf 'Build settings platform: %s\n' "${platform_name:-unknown}"
    printf 'Deployment target: iOS %s\n' "${deployment_target:-unknown}"
    printf 'Development team: %s\n' "${development_team:-not set}"
    printf 'Code signing identity: %s\n' "${code_sign_identity:-unknown}"
    case "$device_family" in
      *1*2*|*2*1*)
        printf 'Target devices: iPhone and iPad (%s)\n' "$device_family"
        ;;
      *)
        printf 'Target devices: %s\n' "${device_family:-unknown}"
        ;;
    esac
    if [[ -n "$app_icon_name" && -f "ios/CourseNavigatorMobile/Resources/Assets.xcassets/${app_icon_name}.appiconset/Contents.json" ]]; then
      printf 'App icon: %s configured\n' "$app_icon_name"
    else
      printf 'App icon: missing or not configured\n'
    fi
  else
    printf 'Build settings: unavailable for scheme %s.\n' "$SCHEME"
  fi
  rm -f "$build_settings"
}

print_ios_app_config() {
  section "iOS App Config"
  if [[ ! -f "$INFO_PLIST_PATH" ]]; then
    printf 'Missing Info.plist: %s\n' "$INFO_PLIST_PATH"
    return
  fi

  local local_network_usage
  local_network_usage="$(plist_raw NSLocalNetworkUsageDescription)"
  if [[ -n "$local_network_usage" ]]; then
    printf 'Local Network usage description: configured\n'
  else
    printf 'Local Network usage description: missing\n'
  fi

  if plutil -extract NSBonjourServices json -o - "$INFO_PLIST_PATH" 2>/dev/null | grep -q '"_coursenav._tcp"'; then
    printf 'Bonjour service _coursenav._tcp: configured\n'
  else
    printf 'Bonjour service _coursenav._tcp: missing\n'
  fi

  case "$(plist_raw NSAppTransportSecurity.NSAllowsLocalNetworking)" in
    true|1|YES)
      printf 'ATS local networking: enabled\n'
      ;;
    *)
      printf 'ATS local networking: not enabled\n'
      ;;
  esac
}

section "Disk"
df -h / || true
if [[ -d "$EXTERNAL_SSD" ]]; then
  df -h "$EXTERNAL_SSD" || true
  check_derived_data_path
else
  printf 'External SSD %s is not mounted.\n' "$EXTERNAL_SSD"
fi

section "Xcode"
if [[ -d /Applications/Xcode.app ]]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
if command -v xcodebuild >/dev/null 2>&1; then
  xcodebuild -version
  if xcodebuild -checkFirstLaunchStatus >/dev/null 2>&1; then
    printf 'Xcode first launch status: ready\n'
  else
    printf 'Xcode first launch status: not complete. Open Xcode once and accept any prompts before installing on device.\n'
  fi
  print_xcode_derived_data_preference
  xcodebuild -showsdks | grep -E 'iphoneos|iphonesimulator' || true
else
  printf 'xcodebuild was not found. Open Xcode once after installation.\n'
fi

print_project_config

print_ios_app_config

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
