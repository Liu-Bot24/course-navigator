cask "course-navigator" do
  version "0.1.8"
  sha256 "0b8e4e715f978140247d1109c52a2369a7c8c34565959556cd9e49c33cd16751"

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
