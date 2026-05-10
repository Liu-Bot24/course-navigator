cask "course-navigator" do
  version "0.1.2"
  sha256 "cb3b06f19e2335f2c92e495472c49ed4a2aeaf52686b206c58f1002cb64b670b"

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
