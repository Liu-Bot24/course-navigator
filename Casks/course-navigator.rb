cask "course-navigator" do
  version "0.1.3"
  sha256 "1834d297dffc278f0d6a104c869fb416987016ac1337644d452c6ed8c2d70ffa"

  url "https://github.com/Liu-Bot24/course-navigator/releases/download/v#{version}/Course.Navigator-#{version}-macos-arm64.dmg",
      verified: "github.com/Liu-Bot24/course-navigator/"
  name "Course Navigator"
  desc "Video course workspace for subtitles, translation, study maps, and ASR"
  homepage "https://github.com/Liu-Bot24/course-navigator"

  depends_on arch: :arm64
  depends_on formula: "node"
  depends_on formula: "python@3.11"
  depends_on formula: "uv"
  depends_on formula: "ffmpeg"

  app "Course Navigator.app"

  caveats <<~EOS
    This app is distributed outside the Mac App Store and may require manual approval on first launch:
      https://github.com/Liu-Bot24/course-navigator/blob/main/docs/mac-install.md
  EOS
end
