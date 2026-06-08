cask "course-navigator" do
  version "0.1.6"
  sha256 "1ab98eef38446c915a32873e347a085eac8ff23149fc44fdfe64a38d4344c6a7"

  url "https://github.com/Liu-Bot24/course-navigator/releases/download/v#{version}/Course.Navigator-#{version}-macos-arm64.dmg"
  name "Course Navigator"
  desc "Video course workspace for subtitles, translation, study maps, and ASR"
  homepage "https://github.com/Liu-Bot24/course-navigator"

  depends_on arch: :arm64

  app "Course Navigator.app"

  caveats <<~EOS
    This app is distributed outside the Mac App Store and may require manual approval on first launch:
      https://github.com/Liu-Bot24/course-navigator/blob/main/docs/mac-install.md
  EOS
end
