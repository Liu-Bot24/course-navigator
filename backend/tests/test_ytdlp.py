import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import course_navigator.ytdlp as ytdlp_module

from course_navigator.config import OnlineAsrServiceConfig, OnlineAsrSettings
from course_navigator.models import DownloadRequest, ExtractRequest, VideoMetadata
from course_navigator.online_asr import (
    _audio_chunks,
    _segments_from_payload,
    _transcribe_chunk,
    extract_online_asr_transcript,
)
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


def test_build_auth_args_for_browser_cookie_mode_can_dump_to_cache(tmp_path):
    cookies_path = tmp_path / "chrome.cookies.txt"
    request = ExtractRequest(
        url="https://www.youtube.com/watch?v=abc",
        mode="browser",
        browser="chrome",
        cookies_path=str(cookies_path),
    )

    assert build_auth_args(request) == ["--cookies", str(cookies_path), "--cookies-from-browser", "chrome"]


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

    assert build_auth_args(request) == ["--cookies", str(Path("/tmp/cookies.txt").expanduser())]


def test_build_auth_args_expands_cookie_file_home():
    request = ExtractRequest(
        url="https://www.youtube.com/watch?v=abc",
        mode="cookies",
        cookies_path="~/cookies.txt",
    )

    assert Path(build_auth_args(request)[1]).name == "cookies.txt"
    assert "~" not in build_auth_args(request)[1]


def test_cookie_file_mode_requires_path():
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="cookies")

    with pytest.raises(ValueError, match="cookies_path"):
        build_auth_args(request)


def test_default_ytdlp_runner_uses_current_python_module(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "abc123",
                "title": "A Lesson",
                "webpage_url": "https://example.com/watch",
                "extractor": "youtube",
                "subtitles": {},
                "automatic_captions": {},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    YtDlpRunner().fetch_metadata(ExtractRequest(url="https://www.youtube.com/watch?v=abc"))

    assert calls[0][:3] == [sys.executable, "-m", "yt_dlp"]


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

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser")

    metadata = runner.fetch_metadata(request)

    assert calls[0][:5] == [
        "yt-dlp",
        "--skip-download",
        "--dump-json",
        "--no-warnings",
        "--ignore-no-formats-error",
    ]
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


def test_fetch_metadata_uses_single_file_fallback_format(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "abc123",
                "title": "A Lesson",
                "webpage_url": "https://www.youtube.com/watch?v=abc",
                "extractor": "youtube",
                "subtitles": {},
                "automatic_captions": {},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    YtDlpRunner(binary="yt-dlp").fetch_metadata(
        ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser", browser="chrome")
    )

    assert "--format" in calls[0]
    assert "--ignore-no-formats-error" in calls[0]
    assert calls[0][calls[0].index("--format") + 1] == "best/bestvideo*+bestaudio/best"
    assert calls[0].index("--format") < calls[0].index("--write-subs")


def test_ytdlp_commands_enable_youtube_challenge_solver_and_single_video_mode(monkeypatch, tmp_path):
    run_calls = []
    popen_calls = []

    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "abc123",
                "title": "A Lesson",
                "webpage_url": "https://www.youtube.com/watch?v=abc",
                "extractor": "youtube",
                "subtitles": {"en": [{"ext": "vtt"}]},
                "automatic_captions": {},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        run_calls.append(cmd)
        if "--write-subs" in cmd and "--dump-json" not in cmd:
            Path(tmp_path, "abc.en.vtt").write_text(
                "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n",
                encoding="utf-8",
            )
        if "--extract-audio" in cmd:
            Path(tmp_path, "abc.wav").write_text("audio", encoding="utf-8")
        return Result()

    class FakeProcess:
        returncode = 0

        def __init__(self, cmd, stdout, stderr, text, **_kwargs):
            popen_calls.append(cmd)
            self.stdout = iter([])

        def wait(self):
            Path(tmp_path, "abc.mp4").write_text("video", encoding="utf-8")
            return self.returncode

        def communicate(self, timeout=None):
            Path(tmp_path, "abc.vtt").write_text(
                "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n",
                encoding="utf-8",
            )
            return "", ""

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/whisper" if name == "whisper" else None)
    monkeypatch.setattr(ytdlp_module, "_probe_video_file", lambda path: {"streams": [{"codec_type": "video"}]})
    monkeypatch.setattr(ytdlp_module, "_ensure_ios_compatible_video", lambda path, progress=None: path)
    runner = YtDlpRunner(binary="yt-dlp")
    extract_request = ExtractRequest(
        url="https://www.youtube.com/watch?v=abc&list=PL123",
        mode="browser",
        browser="chrome",
        language="en",
    )
    download_request = DownloadRequest(
        url="https://www.youtube.com/watch?v=abc&list=PL123",
        mode="browser",
        browser="chrome",
    )

    runner.fetch_metadata(extract_request)
    runner.extract_subtitles(extract_request, tmp_path, make_metadata(language="en", subtitles=["en"], automatic_captions=[]))
    runner.download_video(download_request, tmp_path, "abc")
    runner.extract_asr(extract_request, tmp_path, "abc")

    yt_dlp_commands = [cmd for cmd in [*run_calls, *popen_calls] if cmd[0] == "yt-dlp"]
    assert len(yt_dlp_commands) == 4
    for cmd in yt_dlp_commands:
        assert "--remote-components" in cmd
        assert cmd[cmd.index("--remote-components") + 1] == "ejs:github"
        assert "--no-playlist" in cmd


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

    def fake_run(cmd, capture_output, text, check, **_kwargs):
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


def test_fetch_metadata_retries_without_browser_cookies_when_cookie_database_is_locked(monkeypatch):
    calls = []

    class FailedCookieResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271"

    class MetadataResult:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "abc123",
                "title": "A Public Lesson",
                "webpage_url": "https://www.youtube.com/watch?v=abc",
                "extractor": "youtube",
                "subtitles": {},
                "automatic_captions": {"en": [{"ext": "vtt"}]},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return FailedCookieResult() if len(calls) == 1 else MetadataResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser", browser="chrome")

    metadata = runner.fetch_metadata(request)

    assert metadata.id == "abc123"
    assert "--cookies-from-browser" in calls[0]
    assert "--cookies-from-browser" not in calls[1]


def test_fetch_metadata_saves_browser_cookie_cache_when_configured(monkeypatch, tmp_path):
    calls = []

    class MetadataResult:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "abc123",
                "title": "A Cookie Lesson",
                "webpage_url": "https://www.youtube.com/watch?v=abc",
                "extractor": "youtube",
                "subtitles": {},
                "automatic_captions": {"en": [{"ext": "vtt"}]},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return MetadataResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp", cookie_cache_dir=tmp_path)

    metadata = runner.fetch_metadata(
        ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser", browser="chrome")
    )

    cache_file = tmp_path / "chrome.cookies.txt"
    assert metadata.id == "abc123"
    assert cache_file.exists()
    assert "--cookies" in calls[0]
    assert calls[0][calls[0].index("--cookies") + 1] == str(cache_file)
    assert calls[0][calls[0].index("--cookies-from-browser") + 1] == "chrome"


def test_fetch_metadata_uses_cached_browser_cookies_when_browser_database_is_locked(monkeypatch, tmp_path):
    calls = []
    cache_file = tmp_path / "chrome.cookies.txt"
    cache_file.write_text(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tcached\n",
        encoding="utf-8",
    )

    class FailedCookieResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: Could not copy Chrome cookie database"

    class MetadataResult:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "abc123",
                "title": "Cached Cookie Lesson",
                "webpage_url": "https://www.youtube.com/watch?v=abc",
                "extractor": "youtube",
                "subtitles": {},
                "automatic_captions": {"en": [{"ext": "vtt"}]},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return FailedCookieResult() if len(calls) == 1 else MetadataResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp", cookie_cache_dir=tmp_path)

    metadata = runner.fetch_metadata(
        ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser", browser="chrome")
    )

    assert metadata.id == "abc123"
    assert "--cookies-from-browser" in calls[0]
    assert "--cookies-from-browser" not in calls[1]
    assert calls[1][calls[1].index("--cookies") + 1] == str(cache_file)


def test_fetch_metadata_preserves_cookie_copy_error_when_normal_retry_still_requires_login(monkeypatch):
    calls = []

    class FailedCookieResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271"

    class FailedLoginResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: [youtube] abc: Sign in to confirm you are not a bot"

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return FailedCookieResult() if len(calls) == 1 else FailedLoginResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser", browser="chrome")

    with pytest.raises(YtDlpError, match="无法读取浏览器 Cookie 来源 chrome"):
        runner.fetch_metadata(request)

    assert "--cookies-from-browser" in calls[0]
    assert "--cookies-from-browser" not in calls[1]


def test_fetch_metadata_retries_plain_browser_with_detected_profile_when_login_required(monkeypatch):
    calls = []

    class FailedLoginResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: [youtube] abc: Sign in to confirm you are not a bot"

    class MetadataResult:
        returncode = 0
        stdout = json.dumps(
            {
                "id": "abc123",
                "title": "A Profile Lesson",
                "webpage_url": "https://www.youtube.com/watch?v=abc",
                "extractor": "youtube",
                "subtitles": {},
                "automatic_captions": {"en": [{"ext": "vtt"}]},
            }
        )
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return FailedLoginResult() if len(calls) == 1 else MetadataResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(ytdlp_module, "_browser_cookie_profile_sources", lambda browser: [f"{browser}:Default"])
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser", browser="chrome")

    metadata = runner.fetch_metadata(request)

    assert metadata.id == "abc123"
    assert calls[0][calls[0].index("--cookies-from-browser") + 1] == "chrome"
    assert calls[1][calls[1].index("--cookies-from-browser") + 1] == "chrome:Default"


def test_fetch_metadata_reports_cookie_database_error_from_profile_retry(monkeypatch):
    calls = []

    class FailedLoginResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: [youtube] abc: Sign in to confirm you are not a bot"

    class FailedCookieResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: Could not copy Chrome cookie database"

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return FailedLoginResult()
        if len(calls) == 2:
            return FailedCookieResult()
        return FailedLoginResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(ytdlp_module, "_browser_cookie_profile_sources", lambda browser: [f"{browser}:Default"])
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser", browser="chrome")

    with pytest.raises(YtDlpError, match="无法读取浏览器 Cookie 来源 chrome:Default"):
        runner.fetch_metadata(request)

    assert len(calls) == 3


def test_fetch_metadata_does_not_retry_explicit_browser_profile(monkeypatch):
    calls = []

    class FailedLoginResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: [youtube] abc: Sign in to confirm you are not a bot"

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return FailedLoginResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(ytdlp_module, "_browser_cookie_profile_sources", lambda browser: [f"{browser}:Default"])
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", mode="browser", browser="chrome:Default")

    with pytest.raises(YtDlpError, match="Sign in"):
        runner.fetch_metadata(request)

    assert len(calls) == 1


def test_extract_subtitles_reads_generated_vtt(monkeypatch, tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        Path(tmp_path, "abc.en.vtt").write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n",
            encoding="utf-8",
        )
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    runner = YtDlpRunner(binary="yt-dlp")
    request = ExtractRequest(url="https://www.youtube.com/watch?v=abc", language="en")

    segments = runner.extract_subtitles(request, tmp_path)

    assert "--ignore-no-formats-error" in calls[0]
    assert segments[0].text == "Hi"
    assert segments[0].start == 1.0


def test_extract_subtitles_uses_auto_source_language(monkeypatch, tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
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

    def fake_run(cmd, capture_output, text, check, **_kwargs):
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
    calls: list[list[str]] = []

    class FakeProcess:
        returncode = 0

        def __init__(self, cmd, stdout, stderr, text, **_kwargs):
            calls.append(cmd)
            self.cmd = cmd
            self.stdout = iter([])

        def wait(self):
            Path(tmp_path, "abc.mp4").write_text("video", encoding="utf-8")
            return self.returncode

    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    monkeypatch.setattr(ytdlp_module, "_probe_video_file", lambda path: {
        "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
        "video_codec": "h264",
        "audio_codecs": {"aac"},
        "width": 1280,
        "height": 720,
    })
    monkeypatch.setattr(ytdlp_module, "_ensure_ios_compatible_video", lambda path, progress=None: path)
    runner = YtDlpRunner(binary="yt-dlp")
    request = DownloadRequest(url="https://www.youtube.com/watch?v=abc")

    path = runner.download_video(request, tmp_path, "abc")

    assert path.name == "abc.mp4"
    assert calls[0][calls[0].index("--format") + 1] == ytdlp_module.IOS_COMPATIBLE_DOWNLOAD_FORMAT
    assert calls[0][calls[0].index("--remux-video") + 1] == "mp4"
    assert "--force-overwrites" in calls[0]


def test_download_video_reports_percentage_progress(monkeypatch, tmp_path):
    class FakeProcess:
        returncode = 0

        def __init__(self, cmd, stdout, stderr, text, **_kwargs):
            self.cmd = cmd
            self.stdout = iter(["[download]   7.5% of 10.00MiB\n", "[download] 100% of 10.00MiB\n"])

        def wait(self):
            Path(tmp_path, "abc.mp4").write_text("video", encoding="utf-8")
            return self.returncode

    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    monkeypatch.setattr(ytdlp_module, "_probe_video_file", lambda path: {
        "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
        "video_codec": "h264",
        "audio_codecs": {"aac"},
        "width": 1280,
        "height": 720,
    })
    monkeypatch.setattr(ytdlp_module, "_ensure_ios_compatible_video", lambda path, progress=None: path)
    runner = YtDlpRunner(binary="yt-dlp")
    request = DownloadRequest(url="https://www.youtube.com/watch?v=abc")
    progress: list[int] = []

    path = runner.download_video(request, tmp_path, "abc", progress=lambda value, _message: progress.append(value))

    assert path.name == "abc.mp4"
    assert 7 in progress
    assert 95 in progress or 100 in progress


def test_download_video_merges_newer_bilibili_audio_fragment(monkeypatch, tmp_path):
    class FakeProcess:
        returncode = 0

        def __init__(self, cmd, stdout, stderr, text, **_kwargs):
            self.stdout = iter([])

        def wait(self):
            video = tmp_path / "abc.f30120.mp4"
            audio = tmp_path / "abc.f30280.m4a"
            video.write_bytes(b"video")
            time.sleep(0.01)
            audio.write_bytes(b"audio")
            return self.returncode

    ffmpeg_commands: list[list[str]] = []

    def fake_probe(path: Path):
        if path.name == "abc.f30120.mp4":
            return {
                "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
                "video_codec": "h264",
                "audio_codecs": set(),
                "width": 3840,
                "height": 2160,
            }
        if path.name.startswith(".abc.merged-") or path.name == "abc.mp4":
            return {
                "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
                "video_codec": "h264",
                "audio_codecs": {"aac"},
                "width": 3840,
                "height": 2160,
            }
        raise YtDlpError("缓存视频整理失败：下载结果中没有视频轨道。")

    def fake_ffmpeg(cmd):
        ffmpeg_commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"merged")

    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    monkeypatch.setattr(ytdlp_module, "_probe_video_file", fake_probe)
    monkeypatch.setattr(ytdlp_module, "_run_ffmpeg_or_raise", fake_ffmpeg)
    runner = YtDlpRunner(binary="yt-dlp")
    request = DownloadRequest(url="https://www.bilibili.com/video/BV1abc", mode="browser")

    path = runner.download_video(request, tmp_path, "abc")

    assert path == tmp_path / "abc.mp4"
    assert path.read_bytes() == b"merged"
    assert not (tmp_path / "abc.f30120.mp4").exists()
    assert not (tmp_path / "abc.f30280.m4a").exists()
    assert ffmpeg_commands
    assert str(tmp_path / "abc.f30120.mp4") in ffmpeg_commands[0]
    assert str(tmp_path / "abc.f30280.m4a") in ffmpeg_commands[0]


def test_download_video_prefers_complete_video_over_newer_audio(monkeypatch, tmp_path):
    class FakeProcess:
        returncode = 0

        def __init__(self, cmd, stdout, stderr, text, **_kwargs):
            self.stdout = iter([])

        def wait(self):
            complete = tmp_path / "abc.mp4"
            audio = tmp_path / "abc.f30280.m4a"
            complete.write_bytes(b"complete")
            time.sleep(0.01)
            audio.write_bytes(b"audio")
            return self.returncode

    def fake_probe(path: Path):
        if path.name == "abc.mp4":
            return {
                "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
                "video_codec": "h264",
                "audio_codecs": {"aac"},
                "width": 1920,
                "height": 1080,
            }
        raise YtDlpError("缓存视频整理失败：下载结果中没有视频轨道。")

    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    monkeypatch.setattr(ytdlp_module, "_probe_video_file", fake_probe)
    monkeypatch.setattr(ytdlp_module, "_run_ffmpeg_or_raise", lambda cmd: pytest.fail("should not merge"))
    runner = YtDlpRunner(binary="yt-dlp")
    request = DownloadRequest(url="https://www.bilibili.com/video/BV1abc", mode="browser")

    path = runner.download_video(request, tmp_path, "abc")

    assert path == tmp_path / "abc.mp4"
    assert path.read_bytes() == b"complete"


def test_ensure_ios_compatible_video_remuxes_mpegts_h264_aac(monkeypatch, tmp_path):
    source = tmp_path / "abc.mp4"
    source.write_bytes(b"mpegts")
    calls: list[list[str]] = []
    probe_count = 0

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        nonlocal probe_count
        calls.append(cmd)
        if Path(cmd[0]).name == "ffprobe":
            probe_count += 1
            format_name = "mpegts" if probe_count == 1 else "mov,mp4,m4a,3gp,3g2,mj2"
            return type("Result", (), {
                "returncode": 0,
                "stderr": "",
                "stdout": json.dumps({
                    "format": {"format_name": format_name},
                    "streams": [
                        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
                        {"codec_type": "audio", "codec_name": "aac"},
                    ],
                }),
            })()
        if Path(cmd[0]).name == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"mp4")
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        raise AssertionError(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = ytdlp_module._ensure_ios_compatible_video(source)

    assert result == source
    assert source.read_bytes() == b"mp4"
    ffmpeg_cmd = next(cmd for cmd in calls if Path(cmd[0]).name == "ffmpeg")
    assert "-c" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-c") + 1] == "copy"
    assert "-movflags" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-movflags") + 1] == "+faststart"


def test_ensure_ios_compatible_video_transcodes_webm_to_h264_mp4(monkeypatch, tmp_path):
    source = tmp_path / "abc.webm"
    source.write_bytes(b"webm")
    calls: list[list[str]] = []
    probe_count = 0

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        nonlocal probe_count
        calls.append(cmd)
        if Path(cmd[0]).name == "ffprobe":
            probe_count += 1
            if probe_count == 1:
                payload = {
                    "format": {"format_name": "matroska,webm"},
                    "streams": [
                        {"codec_type": "video", "codec_name": "vp9", "width": 1280, "height": 720},
                        {"codec_type": "audio", "codec_name": "opus"},
                    ],
                }
            else:
                payload = {
                    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
                    "streams": [
                        {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
                        {"codec_type": "audio", "codec_name": "aac"},
                    ],
                }
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": json.dumps(payload)})()
        if Path(cmd[0]).name == "ffmpeg" and cmd[1:] == ["-hide_banner", "-encoders"]:
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": " V....D libx264 H.264 encoder"})()
        if Path(cmd[0]).name == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"mp4")
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        raise AssertionError(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = ytdlp_module._ensure_ios_compatible_video(source)

    assert result == tmp_path / "abc.mp4"
    assert result.read_bytes() == b"mp4"
    assert not source.exists()
    ffmpeg_cmd = [cmd for cmd in calls if Path(cmd[0]).name == "ffmpeg" and "-hide_banner" not in cmd][0]
    assert "-c:v" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-c:v") + 1] == "libx264"
    assert "-c:a" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-c:a") + 1] == "aac"


def test_prepare_ios_compatible_video_copy_returns_compatible_source_without_copy(monkeypatch, tmp_path):
    source = tmp_path / "NAS Lesson.mp4"
    source.write_bytes(b"mp4")
    output = tmp_path / "downloads" / "device-compatible" / "NAS-Lesson.mp4"
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        if Path(cmd[0]).name == "ffprobe":
            payload = {
                "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": json.dumps(payload)})()
        raise AssertionError(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = YtDlpRunner().prepare_ios_compatible_video_copy(source, output)

    assert result == source
    assert source.read_bytes() == b"mp4"
    assert not output.exists()
    assert len(calls) == 1


def test_prepare_ios_compatible_video_copy_transcodes_hevc_without_mutating_source(monkeypatch, tmp_path):
    source = tmp_path / "NAS Lesson.mp4"
    source.write_bytes(b"hevc")
    output = tmp_path / "downloads" / "device-compatible" / "NAS-Lesson.mp4"
    calls: list[list[str]] = []
    probe_count = 0

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        nonlocal probe_count
        calls.append(cmd)
        if Path(cmd[0]).name == "ffprobe":
            probe_count += 1
            video_codec = "hevc" if probe_count == 1 else "h264"
            payload = {
                "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
                "streams": [
                    {"codec_type": "video", "codec_name": video_codec, "width": 1920, "height": 1080},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": json.dumps(payload)})()
        if Path(cmd[0]).name == "ffmpeg" and cmd[1:] == ["-hide_banner", "-encoders"]:
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": " V....D libx264 H.264 encoder"})()
        if Path(cmd[0]).name == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"h264")
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        raise AssertionError(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = YtDlpRunner().prepare_ios_compatible_video_copy(source, output)

    assert result == output
    assert source.read_bytes() == b"hevc"
    assert output.read_bytes() == b"h264"
    ffmpeg_cmd = [cmd for cmd in calls if Path(cmd[0]).name == "ffmpeg" and "-hide_banner" not in cmd][0]
    assert "-c:v" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-c:v") + 1] == "libx264"
    assert "-c:a" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-c:a") + 1] == "aac"


def test_prepare_ios_compatible_video_copy_serializes_duplicate_transcodes(monkeypatch, tmp_path):
    source = tmp_path / "NAS Lesson.mp4"
    source.write_bytes(b"hevc")
    output = tmp_path / "downloads" / "device-compatible" / "NAS-Lesson.mp4"
    write_started = threading.Event()
    writes: list[Path] = []

    hevc_probe = {
        "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
        "video_codec": "hevc",
        "audio_codecs": {"aac"},
        "width": 1920,
        "height": 1080,
    }
    h264_probe = {
        "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
        "video_codec": "h264",
        "audio_codecs": {"aac"},
        "width": 1920,
        "height": 1080,
    }

    def fake_probe(path: Path):
        if path == output and output.exists():
            return h264_probe
        return hevc_probe

    def fake_write(source_path, output_path, probe, progress=None, delete_source=False):
        writes.append(output_path)
        write_started.set()
        time.sleep(0.1)
        output_path.write_bytes(b"h264")
        return output_path

    monkeypatch.setattr(ytdlp_module, "_probe_video_file", fake_probe)
    monkeypatch.setattr(ytdlp_module, "_write_ios_compatible_video", fake_write)

    runner = YtDlpRunner()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runner.prepare_ios_compatible_video_copy, source, output)
        assert write_started.wait(timeout=1)
        second = pool.submit(runner.prepare_ios_compatible_video_copy, source, output)
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert results == [output, output]
    assert writes == [output]


def test_prepare_ios_compatible_video_copy_limits_parallel_transcodes(monkeypatch, tmp_path):
    sources = [tmp_path / "NAS Lesson 1.mp4", tmp_path / "NAS Lesson 2.mp4"]
    outputs = [
        tmp_path / "downloads" / "device-compatible" / "NAS-Lesson-1.mp4",
        tmp_path / "downloads" / "device-compatible" / "NAS-Lesson-2.mp4",
    ]
    for index, source in enumerate(sources):
        source.write_bytes(f"hevc-{index}".encode("utf-8"))

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    hevc_probe = {
        "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
        "video_codec": "hevc",
        "audio_codecs": {"aac"},
        "width": 1920,
        "height": 1080,
    }
    h264_probe = {
        "format_names": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
        "video_codec": "h264",
        "audio_codecs": {"aac"},
        "width": 1920,
        "height": 1080,
    }

    def fake_probe(path: Path):
        if path.exists() and (
            path in outputs
            or ".ios-compatible-" in path.name
        ):
            return h264_probe
        return hevc_probe

    def fake_transcode(source_path, output_path, probe):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.1)
        output_path.write_bytes(b"h264")
        with active_lock:
            active -= 1

    monkeypatch.setattr(ytdlp_module, "_probe_video_file", fake_probe)
    monkeypatch.setattr(ytdlp_module, "_transcode_to_ios_h264", fake_transcode)

    runner = YtDlpRunner()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(runner.prepare_ios_compatible_video_copy, source, output)
            for source, output in zip(sources, outputs)
        ]
        results = [future.result(timeout=2) for future in futures]

    assert results == outputs
    assert max_active == 1


def test_target_h264_bitrate_keeps_device_cache_reasonable_for_course_video():
    assert ytdlp_module._target_h264_bitrate({"width": 1920, "height": 1080}) == "1800k"
    assert ytdlp_module._target_h264_bitrate({"width": 1280, "height": 720}) == "1200k"
    assert ytdlp_module._target_h264_bitrate({"width": 640, "height": 360}) == "900k"


def test_download_video_explains_missing_ffmpeg(monkeypatch, tmp_path):
    class FakeProcess:
        def __init__(self, cmd, stdout, stderr, text, **_kwargs):
            self.stdout = iter(["ERROR: ffmpeg not found. Please install or provide --ffmpeg-location\n"])

        def wait(self):
            return 1

    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    runner = YtDlpRunner(binary="yt-dlp")
    request = DownloadRequest(url="https://www.youtube.com/watch?v=abc")

    with pytest.raises(YtDlpError, match="缺少 ffmpeg"):
        runner.download_video(request, tmp_path, "abc")


def test_probe_local_video_duration_returns_none_when_ffprobe_is_missing(monkeypatch, tmp_path):
    source = tmp_path / "Lesson.mp4"
    source.write_bytes(b"video")

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert YtDlpRunner().probe_local_video_duration(source) is None


def test_extract_asr_reports_progress_and_simplifies_chinese(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        if "--extract-audio" in cmd:
            Path(tmp_path, "abc.wav").write_text("audio", encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    class FakeProcess:
        returncode = 0

        def __init__(self, cmd, stdout, stderr, text, **_kwargs):
            calls.append(cmd)
            Path(tmp_path, "abc.vtt").write_text(
                "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n這是一個測試\n",
                encoding="utf-8",
            )

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("subprocess.Popen", FakeProcess)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/whisper" if name == "whisper" else None)
    runner = YtDlpRunner(binary="yt-dlp")
    progress: list[int] = []

    result = runner.extract_asr(
        ExtractRequest(url="https://www.youtube.com/watch?v=abc", subtitle_source="asr"),
        tmp_path,
        "abc",
        progress=lambda value, _message: progress.append(value),
    )

    assert result[0].text == "这是一个测试"
    assert progress[0] == 3
    assert max(progress) >= 90


def test_online_asr_extracts_and_compresses_audio_before_transcription(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        if "--extract-audio" in cmd:
            (tmp_path / "abc.online-source.wav").write_text("audio", encoding="utf-8")
        elif cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"mp3")
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(
        "course_navigator.online_asr._transcribe_chunk",
        lambda provider, service, audio_path, language: {
            "segments": [{"start": 0.0, "end": 1.5, "text": "online transcript"}]
        },
    )

    result = extract_online_asr_transcript(
        ExtractRequest(url="https://www.youtube.com/watch?v=abc", subtitle_source="online_asr"),
        tmp_path,
        "abc",
        "yt-dlp",
        OnlineAsrSettings(provider="xai", xai={"api_key": "xai-test"}),
    )

    yt_dlp_cmd = next(cmd for cmd in calls if cmd[0] == "yt-dlp")
    assert "--remote-components" in yt_dlp_cmd
    assert yt_dlp_cmd[yt_dlp_cmd.index("--remote-components") + 1] == "ejs:github"
    assert "--no-playlist" in yt_dlp_cmd
    ffmpeg_cmd = next(cmd for cmd in calls if cmd[0] == "ffmpeg")
    assert "-b:a" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-b:a") + 1] == "64k"
    assert result[0].text == "online transcript"


def test_online_asr_retries_plain_browser_with_profile_when_login_required(monkeypatch, tmp_path):
    calls = []

    class FailedLoginResult:
        returncode = 1
        stdout = ""
        stderr = "ERROR: [youtube] abc: Sign in to confirm you are not a bot"

    class SuccessResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        if "--extract-audio" in cmd:
            if len([call for call in calls if "--extract-audio" in call]) == 1:
                return FailedLoginResult()
            (tmp_path / "abc.online-source.wav").write_text("audio", encoding="utf-8")
            return SuccessResult()
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"mp3")
        return SuccessResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(ytdlp_module, "_browser_cookie_profile_sources", lambda browser: [f"{browser}:Default"])
    monkeypatch.setattr(
        "course_navigator.online_asr._transcribe_chunk",
        lambda provider, service, audio_path, language: {
            "segments": [{"start": 0.0, "end": 1.5, "text": "online transcript"}]
        },
    )

    result = extract_online_asr_transcript(
        ExtractRequest(
            url="https://www.youtube.com/watch?v=abc",
            mode="browser",
            browser="chrome",
            subtitle_source="online_asr",
        ),
        tmp_path,
        "abc",
        "yt-dlp",
        OnlineAsrSettings(provider="xai", xai={"api_key": "xai-test"}),
    )

    yt_dlp_calls = [cmd for cmd in calls if "--extract-audio" in cmd]
    assert yt_dlp_calls[0][yt_dlp_calls[0].index("--cookies-from-browser") + 1] == "chrome"
    assert yt_dlp_calls[1][yt_dlp_calls[1].index("--cookies-from-browser") + 1] == "chrome:Default"
    assert result[0].text == "online transcript"


def test_online_asr_defaults_to_current_python_ytdlp_module(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        if "--extract-audio" in cmd:
            (tmp_path / "abc.online-source.wav").write_text("audio", encoding="utf-8")
        elif cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"mp3")
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(
        "course_navigator.online_asr._transcribe_chunk",
        lambda provider, service, audio_path, language: {
            "segments": [{"start": 0.0, "end": 1.5, "text": "online transcript"}]
        },
    )

    extract_online_asr_transcript(
        ExtractRequest(url="https://www.youtube.com/watch?v=abc", subtitle_source="online_asr"),
        tmp_path,
        "abc",
        None,
        OnlineAsrSettings(provider="xai", xai={"api_key": "xai-test"}),
    )

    assert calls[0][:3] == [sys.executable, "-m", "yt_dlp"]


def test_online_asr_turns_provider_http_errors_into_user_errors(monkeypatch, tmp_path):
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"mp3")

    class FakeResponse:
        status_code = 401
        headers = {"content-type": "application/json"}
        text = '{"error":{"message":"bad auth"}}'

        def json(self):
            return {"error": {"message": "bad auth"}}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(YtDlpError, match="HTTP 401.*bad auth"):
        _transcribe_chunk("openai", OnlineAsrServiceConfig(api_key="secret"), audio, "zh-CN")


def test_xai_online_asr_omits_format_when_language_is_auto(monkeypatch, tmp_path):
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"mp3")
    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = "{}"

        def json(self):
            return {"words": [{"word": "hello", "start": 0, "end": 0.5}]}

    def fake_post(endpoint, headers, data, files, timeout):
        captured["endpoint"] = endpoint
        captured["data"] = dict(data)
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    payload = _transcribe_chunk("xai", OnlineAsrServiceConfig(api_key="secret"), audio, "auto")

    assert payload == {"words": [{"word": "hello", "start": 0, "end": 0.5}]}
    assert captured["endpoint"] == "https://api.x.ai/v1/stt"
    assert "format" not in captured["data"]
    assert "language" not in captured["data"]


def test_xai_online_asr_uses_format_only_for_supported_language(monkeypatch, tmp_path):
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"mp3")
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = "{}"

        def json(self):
            return {"words": [{"word": "hello", "start": 0, "end": 0.5}]}

    def fake_post(endpoint, headers, data, files, timeout):
        calls.append(dict(data))
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    _transcribe_chunk("xai", OnlineAsrServiceConfig(api_key="secret"), audio, "en")
    _transcribe_chunk("xai", OnlineAsrServiceConfig(api_key="secret"), audio, "zh-CN")

    assert calls[0]["language"] == "en"
    assert calls[0]["format"] == "true"
    assert "language" not in calls[1]
    assert "format" not in calls[1]


def test_online_asr_splits_large_compressed_audio(monkeypatch, tmp_path):
    audio = tmp_path / "lesson.mp3"
    audio.write_bytes(b"0" * 101)
    chunks_created = []

    def fake_duration(path):
        return 120.0

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        chunk_path = Path(cmd[-1])
        chunk_path.write_bytes(b"chunk")
        chunks_created.append(chunk_path)
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("course_navigator.online_asr._audio_duration", fake_duration)
    monkeypatch.setattr("subprocess.run", fake_run)

    chunks = _audio_chunks(audio, "lesson", tmp_path, limit_bytes=50)

    assert len(chunks) == 3
    assert chunks[0][1] == 0.0
    assert chunks[1][1] < 40.1
    assert all(path.exists() for path in chunks_created)


def test_online_asr_parses_segment_and_word_timestamp_payloads():
    segment_result = _segments_from_payload(
        {"segments": [{"start": 1.0, "end": 2.0, "text": "Segment text"}]},
        offset=10,
    )
    word_result = _segments_from_payload(
        {
            "words": [
                {"word": "你", "start": 0.0, "end": 0.2},
                {"word": "好", "start": 0.2, "end": 0.4},
            ]
        },
        offset=3,
    )

    assert segment_result[0].start == 11
    assert segment_result[0].text == "Segment text"
    assert word_result[0].start == 3
    assert word_result[0].text == "你好"


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
