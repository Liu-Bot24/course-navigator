import json
from pathlib import Path

import pytest
import course_navigator.ytdlp as ytdlp_module

from course_navigator.models import DownloadRequest, ExtractRequest, VideoMetadata
from course_navigator.ytdlp import (
    YtDlpError,
    YtDlpRunner,
    build_auth_args,
    choose_source_subtitle_language,
)


def test_build_auth_args_for_normal_mode():
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="normal")

    assert build_auth_args(request) == []


def test_build_auth_args_for_browser_cookie_mode():
    request = ExtractRequest(
        url="https://www.youtube.com/watch?v=abc",
        mode="browser",
        browser="chrome",
    )

    assert build_auth_args(request) == ["--cookies-from-browser", "chrome"]


def test_build_auth_args_defaults_blank_browser_to_chrome():
    request = ExtractRequest(
        url="https://www.youtube.com/watch?v=abc",
        mode="browser",
        browser="  ",
    )

    assert build_auth_args(request) == ["--cookies-from-browser", "chrome"]


def test_build_auth_args_for_cookie_file_mode():
    request = ExtractRequest(
        url="https://www.youtube.com/watch?v=abc",
        mode="cookies",
        cookies_path="/tmp/cookies.txt",
    )

    assert build_auth_args(request) == ["--cookies", "/tmp/cookies.txt"]


def test_build_auth_args_expands_cookie_file_home():
    request = ExtractRequest(
        url="https://www.youtube.com/watch?v=abc",
        mode="cookies",
        cookies_path="~/cookies.txt",
    )

    assert build_auth_args(request)[1].endswith("/cookies.txt")
    assert "~" not in build_auth_args(request)[1]


def test_cookie_file_mode_requires_path():
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="cookies")

    with pytest.raises(ValueError, match="cookies_path"):
        build_auth_args(request)


def test_fetch_metadata_parses_ytdlp_json(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "abc123",
                "title": "A Lesson",
                "duration": 125,
                "uploader": "Lesson Uploader",
                "channel": "Lesson Channel",
                "creator": "Lesson Creator",
                "description": "Lesson summary with trusted course terms.",
                "playlist_title": "A Course",
                "playlist_index": 3,
                "webpage_url": "https://example.com/watch",
                "extractor": "youtube",
                "url": "https://cdn.example.com/video.m3u8",
                "language": "en",
                "subtitles": {"en": [{"ext": "vtt"}]},
                "automatic_captions": {"zh-Hans": [{"ext": "vtt"}]},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser")

    metadata = runner.fetch_metadata(request)

    assert calls[0][:4] == ["yt-dlp", "--skip-download", "--dump-json", "--no-warnings"]
    assert "--write-subs" in calls[0]
    assert "--write-auto-subs" in calls[0]
    assert calls[0][calls[0].index("--sub-langs") + 1] == "all"
    assert "--cookies-from-browser" in calls[0]
    assert metadata.id == "abc123"
    assert metadata.title == "A Lesson"
    assert metadata.uploader == "Lesson Uploader"
    assert metadata.channel == "Lesson Channel"
    assert metadata.creator == "Lesson Creator"
    assert metadata.description == "Lesson summary with trusted course terms."
    assert metadata.playlist_title == "A Course"
    assert metadata.playlist_index == 3
    assert metadata.language == "en"
    assert metadata.stream_url == "https://cdn.example.com/video.m3u8"
    assert metadata.subtitles == ["en"]
    assert metadata.automatic_captions == ["zh-Hans"]


def test_fetch_metadata_keeps_bilibili_subtitles_visible(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "BV1iVoVBgERD",
                "title": "A Bili Lesson",
                "duration": 12818,
                "webpage_url": "https://www.bilibili.com/video/BV1iVoVBgERD/",
                "extractor": "BiliBili",
                "language": "zh",
                "subtitles": {"danmaku": [{"ext": "xml"}], "ai-zh": [{"ext": "srt"}]},
                "automatic_captions": {},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.bilibili.com/video/BV1iVoVBgERD/", mode="browser")

    metadata = runner.fetch_metadata(request)

    assert "--write-subs" in calls[0]
    assert metadata.subtitles == ["ai-zh", "danmaku"]


def test_choose_source_subtitle_language_prefers_metadata_language():
    metadata = make_metadata(language="ja", subtitles=["en", "ja"], automatic_captions=["zh-Hans"])

    assert choose_source_subtitle_language(metadata) == "ja"


def test_choose_source_subtitle_language_matches_language_family():
    metadata = make_metadata(language="zh", subtitles=["en", "zh-Hans"], automatic_captions=[])

    assert choose_source_subtitle_language(metadata) == "zh-Hans"


def test_choose_source_subtitle_language_skips_danmaku():
    metadata = make_metadata(language="zh", subtitles=["danmaku", "ai-zh"], automatic_captions=[])

    assert choose_source_subtitle_language(metadata) == "ai-zh"


def test_choose_source_subtitle_language_prefers_chinese_for_bilibili_without_metadata_language():
    metadata = make_metadata(
        language=None,
        subtitles=["ai-ar", "ai-en", "ai-es", "ai-ja", "ai-pt", "ai-zh", "danmaku"],
        automatic_captions=[],
        title="【示例作者】这节课解释视觉现象",
        extractor="BiliBili",
    )

    assert choose_source_subtitle_language(metadata) == "ai-zh"


def test_choose_source_subtitle_language_retries_all_when_only_danmaku_is_visible():
    metadata = make_metadata(language="zh", subtitles=["danmaku"], automatic_captions=[])

    assert choose_source_subtitle_language(metadata) == "all,-danmaku,-live_chat,-comments,-rechat"


def test_choose_source_subtitle_language_keeps_explicit_override():
    metadata = make_metadata(language="en", subtitles=["en"], automatic_captions=["zh-Hans"])

    assert choose_source_subtitle_language(metadata, requested="zh-Hans") == "zh-Hans"


def test_fetch_metadata_does_not_use_video_only_split_stream(monkeypatch):
    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "BV1iVoVBgERD",
                "title": "A Bili Lesson",
                "duration": 12818,
                "webpage_url": "https://www.bilibili.com/video/BV1iVoVBgERD/",
                "extractor": "BiliBili",
                "requested_formats": [
                    {"url": "https://cdn.example.com/video.m4s", "vcodec": "av01", "acodec": "none"},
                    {"url": "https://cdn.example.com/audio.m4s", "vcodec": "none", "acodec": "mp4a.40.2"},
                ],
                "formats": [
                    {"url": "https://cdn.example.com/video.m4s", "vcodec": "av01", "acodec": "none"},
                    {"url": "https://cdn.example.com/audio.m4s", "vcodec": "none", "acodec": "mp4a.40.2"},
                ],
                "subtitles": {"ai-zh": [{"ext": "srt"}]},
                "automatic_captions": {},
            }
        )
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.bilibili.com/video/BV1iVoVBgERD/", mode="browser")

    metadata = runner.fetch_metadata(request)

    assert metadata.stream_url is None


def test_fetch_metadata_raises_useful_error(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "Sign in to confirm you are not a bot"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc")

    with pytest.raises(YtDlpError, match="Sign in"):
        runner.fetch_metadata(request)


def test_extract_subtitles_reads_generated_vtt(monkeypatch, tmp_path):
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, check):
        Path(tmp_path, "abc.en.vtt").write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n",
            encoding="utf-8",
        )
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", language="en")

    segments = runner.extract_subtitles(request, tmp_path)

    assert segments[0].text == "Hi"
    assert segments[0].start == 1.0


def test_extract_subtitles_uses_auto_source_language(monkeypatch, tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        Path(tmp_path, "abc.ja.vtt").write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nこんにちは\n",
            encoding="utf-8",
        )
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc")
    metadata = make_metadata(language="ja", subtitles=["en", "ja"], automatic_captions=[])

    segments = runner.extract_subtitles(request, tmp_path, metadata)

    assert calls[0][calls[0].index("--sub-langs") + 1] == "ja"
    assert segments[0].text == "こんにちは"


def test_extract_subtitles_clears_stale_subtitle_files(monkeypatch, tmp_path):
    Path(tmp_path, "abc.ai-ar.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nمرحبا\n",
        encoding="utf-8",
    )

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, check):
        Path(tmp_path, "abc.ai-zh.vtt").write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n你好\n",
            encoding="utf-8",
        )
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.bilibili.com/video/BVabc/")
    metadata = make_metadata(
        language=None,
        subtitles=["ai-ar", "ai-zh", "danmaku"],
        automatic_captions=[],
        title="中文视频",
        extractor="BiliBili",
    )

    segments = runner.extract_subtitles(request, tmp_path, metadata)

    assert segments[0].text == "你好"
    assert not Path(tmp_path, "abc.ai-ar.vtt").exists()


def test_extract_subtitles_falls_back_to_hls_manifest_tracks(monkeypatch, tmp_path):
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_download_text(url: str) -> str:
        if url == "https://cdn.example.com/master.m3u8":
            return (
                "#EXTM3U\n"
                '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en-Us",'
                'URI="subs/en.m3u8"\n'
            )
        if url == "https://cdn.example.com/subs/en.m3u8":
            return "#EXTM3U\n#EXTINF:10.0,\nlesson.vtt\n#EXT-X-ENDLIST\n"
        if url == "https://cdn.example.com/subs/lesson.vtt":
            return "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello from HLS\n"
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(ytdlp_module, "_download_text", fake_download_text)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://example.com/lesson")
    metadata = make_metadata(language="en", subtitles=[], automatic_captions=[])
    metadata.hls_manifest_url = "https://cdn.example.com/master.m3u8"

    segments = runner.extract_subtitles(request, tmp_path, metadata)

    assert segments[0].text == "Hello from HLS"
    assert segments[0].start == 1.0
    assert list(tmp_path.glob("*.hls.vtt"))


def test_download_video_returns_generated_video(monkeypatch, tmp_path):
    class FakeProcess:
        returncode = 0

        def __init__(self, cmd, stdout, stderr, text):
            self.cmd = cmd
            self.stdout = iter([])

        def wait(self):
            Path(tmp_path, "abc.mp4").write_text("video", encoding="utf-8")
            return self.returncode

    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    runner = YtDlpRunner(binary="yt-dlp")
    request = DownloadRequest(url="https://www.youtube.com/watch?v=abc")

    path = runner.download_video(request, tmp_path, "abc")

    assert path.name == "abc.mp4"


def test_download_video_reports_percentage_progress(monkeypatch, tmp_path):
    class FakeProcess:
        returncode = 0

        def __init__(self, cmd, stdout, stderr, text):
            self.cmd = cmd
            self.stdout = iter(["[download]   7.5% of 10.00MiB\n", "[download] 100% of 10.00MiB\n"])

        def wait(self):
            Path(tmp_path, "abc.mp4").write_text("video", encoding="utf-8")
            return self.returncode

    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    runner = YtDlpRunner(binary="yt-dlp")
    request = DownloadRequest(url="https://www.youtube.com/watch?v=abc")
    progress: list[int] = []

    path = runner.download_video(request, tmp_path, "abc", progress=lambda value, _message: progress.append(value))

    assert path.name == "abc.mp4"
    assert 7 in progress
    assert 95 in progress or 100 in progress


def test_download_video_explains_missing_ffmpeg(monkeypatch, tmp_path):
    class FakeProcess:
        def __init__(self, cmd, stdout, stderr, text):
            self.stdout = iter(["ERROR: ffmpeg not found. Please install or provide --ffmpeg-location\n"])

        def wait(self):
            return 1

    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    runner = YtDlpRunner(binary="yt-dlp")
    request = DownloadRequest(url="https://www.youtube.com/watch?v=abc")

    with pytest.raises(YtDlpError, match="缺少 ffmpeg"):
        runner.download_video(request, tmp_path, "abc")


def test_find_newest_subtitle_handles_removed_directory(tmp_path):
    assert ytdlp_module._find_newest_subtitle(tmp_path / "removed") is None


def make_metadata(
    language: str | None,
    subtitles: list[str],
    automatic_captions: list[str],
    title: str = "A Lesson",
    extractor: str = "youtube",
) -> VideoMetadata:
    return VideoMetadata(
        id="abc123",
        title=title,
        duration=125,
        webpage_url="https://example.com/watch",
        extractor=extractor,
        language=language,
        subtitles=subtitles,
        automatic_captions=automatic_captions,
    )
