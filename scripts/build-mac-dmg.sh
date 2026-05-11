#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Course Navigator"
VERSION="$(node -e "console.log(require('$ROOT_DIR/launcher/src-tauri/tauri.conf.json').version)")"
ARCH="$(uname -m)"
APP_PATH="$ROOT_DIR/launcher/src-tauri/target/release/bundle/macos/$APP_NAME.app"
OUTPUT_DIR="$ROOT_DIR/dist/mac"
DMG_FILE_STEM="${APP_NAME// /.}-$VERSION-macos-$ARCH"
DMG_BASENAME="$DMG_FILE_STEM.dmg"
DMG_PATH="$OUTPUT_DIR/$DMG_BASENAME"
TMP_DMG_PATH="$OUTPUT_DIR/$DMG_FILE_STEM.tmp.dmg"
MOUNT_DIR=""

cleanup() {
  if [[ -n "$MOUNT_DIR" && -d "$MOUNT_DIR" ]]; then
    hdiutil detach "$MOUNT_DIR" >/dev/null 2>&1 || true
  fi
  rm -f "$TMP_DMG_PATH"
}
trap cleanup EXIT

create_dmg_background() {
  local background_path="$1"
  if command -v swift >/dev/null 2>&1; then
    swift - "$background_path" <<'SWIFT'
import AppKit

let output = CommandLine.arguments[1]
let width: CGFloat = 620
let height: CGFloat = 360
let image = NSImage(size: NSSize(width: width, height: height))

func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat, _ alpha: CGFloat = 1) -> NSColor {
    NSColor(calibratedRed: red / 255, green: green / 255, blue: blue / 255, alpha: alpha)
}

image.lockFocus()
let bounds = NSRect(x: 0, y: 0, width: width, height: height)
let gradient = NSGradient(starting: color(247, 248, 251), ending: color(237, 241, 247))
gradient?.draw(in: bounds, angle: -90)

let paragraph = NSMutableParagraphStyle()
paragraph.alignment = .center

let titleAttributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 24, weight: .semibold),
    .foregroundColor: color(31, 41, 55),
    .paragraphStyle: paragraph
]
let subtitleAttributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 15, weight: .regular),
    .foregroundColor: color(107, 114, 128),
    .paragraphStyle: paragraph
]

("拖到 Applications 安装" as NSString).draw(
    in: NSRect(x: 0, y: 300, width: width, height: 34),
    withAttributes: titleAttributes
)
("Drag to Applications" as NSString).draw(
    in: NSRect(x: 0, y: 266, width: width, height: 24),
    withAttributes: subtitleAttributes
)

let arrowColor = color(37, 99, 235)
arrowColor.setFill()
let arrow = NSBezierPath()
arrow.move(to: NSPoint(x: 238, y: 146))
arrow.line(to: NSPoint(x: 332, y: 146))
arrow.line(to: NSPoint(x: 332, y: 122))
arrow.line(to: NSPoint(x: 392, y: 158))
arrow.line(to: NSPoint(x: 332, y: 194))
arrow.line(to: NSPoint(x: 332, y: 170))
arrow.line(to: NSPoint(x: 238, y: 170))
arrow.close()
arrow.fill()

image.unlockFocus()

guard
    let tiff = image.tiffRepresentation,
    let bitmap = NSBitmapImageRep(data: tiff),
    let png = bitmap.representation(using: .png, properties: [:])
else {
    fatalError("Unable to render DMG background")
}

try png.write(to: URL(fileURLWithPath: output))
SWIFT
    return
  fi

  python3 - "$background_path" <<'PY'
import struct
import sys
import zlib

output = sys.argv[1]
width, height = 620, 360

pixels = bytearray()
for y in range(height):
    pixels.append(0)
    shade = 248 - int(y * 10 / height)
    for x in range(width):
        r, g, b = shade, shade + 1, min(shade + 4, 255)
        if 252 <= x <= 370 and 177 <= y <= 187:
            r, g, b = 37, 99, 235
        if x >= 332 and 158 <= y <= 206 and abs(y - 182) <= (370 - x) * 0.65:
            r, g, b = 37, 99, 235
        pixels.extend((r, g, b))

def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

with open(output, "wb") as handle:
    handle.write(b"\x89PNG\r\n\x1a\n")
    handle.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    handle.write(chunk(b"IDAT", zlib.compress(bytes(pixels), 9)))
    handle.write(chunk(b"IEND", b""))
PY
}

configure_dmg_window() {
  local volume_name="$1"
  local mount_dir="$2"
  osascript <<APPLESCRIPT
tell application "Finder"
  tell disk "$volume_name"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {120, 120, 740, 480}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 96
    set background picture of viewOptions to file ".background:background.png"
    set position of item "$APP_NAME.app" of container window to {160, 200}
    set position of item "Applications" of container window to {460, 200}
    update without registering applications
    delay 1
    close
  end tell
end tell
APPLESCRIPT
}

npm --prefix "$ROOT_DIR/launcher" run tauri:build

if [[ ! -d "$APP_PATH" ]]; then
  echo "Missing built app: $APP_PATH" >&2
  exit 1
fi

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_PATH"
fi

mkdir -p "$OUTPUT_DIR"
rm -f "$DMG_PATH" "$DMG_PATH.sha256" "$TMP_DMG_PATH"

hdiutil create \
  -volname "$APP_NAME" \
  -size 160m \
  -fs HFS+ \
  -type UDIF \
  -ov \
  "$TMP_DMG_PATH" >/dev/null

if [[ -d "/Volumes/$APP_NAME" ]]; then
  hdiutil detach "/Volumes/$APP_NAME" >/dev/null 2>&1 || true
fi

ATTACH_PLIST="$(mktemp /tmp/course-navigator-dmg-attach.XXXXXX.plist)"
hdiutil attach \
  -readwrite \
  -noverify \
  -noautoopen \
  -plist \
  "$TMP_DMG_PATH" >"$ATTACH_PLIST"
MOUNT_DIR="$(python3 - "$ATTACH_PLIST" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as handle:
    payload = plistlib.load(handle)
for entity in payload.get("system-entities", []):
    mount_point = entity.get("mount-point")
    if mount_point:
        print(mount_point)
        break
PY
)"
rm -f "$ATTACH_PLIST"
if [[ -z "$MOUNT_DIR" ]]; then
  echo "Unable to mount temporary DMG" >&2
  exit 1
fi

ditto "$APP_PATH" "$MOUNT_DIR/$APP_NAME.app"
ln -s /Applications "$MOUNT_DIR/Applications"
mkdir -p "$MOUNT_DIR/.background"
create_dmg_background "$MOUNT_DIR/.background/background.png"
chflags hidden "$MOUNT_DIR/.background" >/dev/null 2>&1 || true
if command -v SetFile >/dev/null 2>&1; then
  SetFile -a V "$MOUNT_DIR/.background"
fi
configure_dmg_window "$APP_NAME" "$MOUNT_DIR"
rm -rf "$MOUNT_DIR/.fseventsd" "$MOUNT_DIR/.Trashes"
sync
hdiutil detach "$MOUNT_DIR" >/dev/null
MOUNT_DIR=""

hdiutil convert "$TMP_DMG_PATH" \
  -format UDZO \
  -imagekey zlib-level=9 \
  -o "$DMG_PATH" >/dev/null

(cd "$OUTPUT_DIR" && shasum -a 256 "$DMG_BASENAME" > "$DMG_BASENAME.sha256")
rm -f "$TMP_DMG_PATH"

echo "Created $DMG_PATH"
echo "Created $DMG_PATH.sha256"
echo "This DMG is not notarized. macOS may require manual approval on first open."
