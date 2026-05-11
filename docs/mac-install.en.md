# macOS Local Install

When Course Navigator is provided as a macOS installer, you can install and launch it like a regular Mac app without using the Mac App Store.

## Requirements

- macOS.
- Apple Silicon Mac. The current DMG and Homebrew Cask do not provide an Intel Mac build yet.
- Node.js 20.19+ on the Node 20 line, or Node.js 22.12+ on Node 22 and newer, with npm.
- Python 3.11 or newer.
- `uv` for Python backend dependencies.
- `ffmpeg` for local video cache, audio extraction, and media conversion; it can be installed later if you do not use media conversion features.

With Homebrew:

```bash
brew install node python@3.11 uv ffmpeg
```

## Install The App

The current macOS installer and Homebrew Cask support Apple Silicon Macs. Intel Mac builds are not provided yet.

If you have Homebrew installed, you can install the app from the GitHub release:

```bash
brew tap liu-bot24/course-navigator https://github.com/Liu-Bot24/course-navigator
brew install --cask liu-bot24/course-navigator/course-navigator
```

After installing with Homebrew, quit Course Navigator before upgrading:

```bash
brew update
brew upgrade --cask liu-bot24/course-navigator/course-navigator
```

You can also install it manually:

1. Open `Course.Navigator-<version>-macos-arm64.dmg`.
2. Drag `Course Navigator.app` to `Applications`.
3. Launch Course Navigator from `Applications`.

The Homebrew Cask and DMG use the same app bundle. For an unnotarized build, the first-open steps below apply to both install methods.

On first launch, Course Navigator installs its runtime resources to:

```text
~/Library/Application Support/Course Navigator/
```

Course material is stored in `Workspace` by default. You can change the workspace location in the app.

The first service start installs local runtime dependencies. It needs an internet connection and can take a few minutes. Later starts are faster.

## First Open Prompt

For an unnotarized build, macOS may warn that it cannot verify the developer or check the app for malicious software. If you trust the source of the installer, you can allow it manually:

1. Make sure `Course Navigator.app` is in `Applications`.
2. Try opening Course Navigator.
3. When macOS shows the verification warning, click `Done` to close it. Do not choose `Move to Trash`.
4. Open `System Settings`.
5. Go to `Privacy & Security`.
6. Choose `Open Anyway` next to the security prompt.
7. When macOS shows the confirmation prompt, choose `Open Anyway` again.

After the first approval, macOS saves the exception and you can open the app normally.

`Open Anyway` is a temporary Gatekeeper override. It usually appears only after you have tried to open the app, and it is available only for a limited time. If you do not see the button, try opening Course Navigator from `Applications` again, then return to `System Settings` → `Privacy & Security`. If the button appears but does not respond, close any Course Navigator warning window first, then click `Open Anyway` again.

## Launchpad Or Apps Does Not Update Immediately

After dragging the app to `Applications`, installation success is determined by whether `/Applications/Course Navigator.app` exists and can be opened from Finder. Launchpad, and the Apps view on newer macOS versions, depend on system indexing and LaunchServices cache, so they may not refresh immediately. This delay is more common when repeatedly deleting and replacing test builds with the same app name and version.

If Course Navigator is already in `Applications` but does not appear in Launchpad or Apps yet, open it directly from Finder's `Applications` folder first. After one successful launch, macOS usually shows it after the next indexing refresh.
