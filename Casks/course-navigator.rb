cask "course-navigator" do
  version "0.1.4"
  sha256 "0d47d57eae7513901d748c5b478d6c730b1f79608d3c3531feab8170c449d671"

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
