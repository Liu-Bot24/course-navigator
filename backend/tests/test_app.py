import json
from pathlib import Path
from time import sleep

from fastapi.testclient import TestClient

import course_navigator.app as app_module
from course_navigator.app import create_app
from course_navigator.config import OnlineAsrSettings, Settings
from course_navigator.library import CourseLibrary
from course_navigator.models import CourseItem, StudyMaterial, TranscriptSegment, VideoMetadata
from course_navigator.ytdlp import YtDlpError


class FakeRunner:
    def fetch_metadata(self, request):
        return VideoMetadata(
            id="abc123",
            title="Sample Lesson",
            duration=42,
            uploader="Sample Teacher",
            channel="Sample Channel",
            creator="Sample Creator",
            description="A course summary mentioning D-tail terminology.",
            webpage_url=str(request.url),
            extractor="youtube",
            stream_url="https://cdn.example.com/sample.m3u8",
            subtitles=["en"],
            automatic_captions=[],
        )

    def extract_subtitles(self, request, target_dir: Path, metadata=None):
        return [
            TranscriptSegment(start=0, end=4, text="Opening idea."),
            TranscriptSegment(start=4, end=8, text="Important detail."),
        ]

    def download_video(self, request, target_dir: Path, item_id: str, progress=None):
        target_dir.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(42, "正在缓存视频")
            sleep(0.03)
        path = target_dir / f"{item_id}.mp4"
        path.write_text("video", encoding="utf-8")
        return path


class FakeLocalVideoRunner(FakeRunner):
    def probe_local_video_duration(self, path: Path):
        return 67.5

    def extract_asr_from_file(self, video_path: Path, target_dir: Path, item_id: str, language: str = "auto", progress=None):
        if progress:
            progress(45, "正在转写本地视频")
        assert video_path.name == "Local-Lesson.mp4"
        return [TranscriptSegment(start=0, end=2, text="Local transcript")]


def test_health_route(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_extract_route_saves_course_item(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "abc123"
    assert payload["title"] == "Sample Lesson"
    assert payload["metadata"]["stream_url"] == "https://cdn.example.com/sample.m3u8"
    assert payload["metadata"]["uploader"] == "Sample Teacher"
    assert payload["metadata"]["channel"] == "Sample Channel"
    assert payload["metadata"]["creator"] == "Sample Creator"
    assert payload["metadata"]["description"] == "A course summary mentioning D-tail terminology."
    assert payload["transcript"][1]["text"] == "Important detail."

    list_response = client.get("/api/items")
    assert list_response.json()[0]["id"] == "abc123"


def test_deeplearning_lesson_url_uses_lesson_slug_as_display_title(tmp_path):
    class DeepLearningRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.title = "AI Prompting for Everyone - DeepLearning.AI (1)"
            metadata.extractor = "generic"
            metadata.webpage_url = str(request.url)
            return metadata

    client = make_client(tmp_path, runner=DeepLearningRunner())

    response = client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/ai-prompting-for-everyone/lesson/53ttu2p0/pretrained-knowledge",
            "mode": "normal",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Pretrained knowledge"
    assert payload["collection_title"] == "AI Prompting For Everyone"


def test_new_lessons_receive_next_course_index_in_collection(tmp_path):
    class LessonRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            url = str(request.url)
            if "second-lesson" in url:
                metadata.id = "second-lesson"
                metadata.title = "Second Lesson"
            else:
                metadata.id = "first-lesson"
                metadata.title = "First Lesson"
            metadata.extractor = "generic"
            metadata.webpage_url = url
            metadata.playlist_index = None
            return metadata

    client = make_client(tmp_path, runner=LessonRunner())
    first = client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/example-course/lesson/a1/first-lesson",
            "mode": "normal",
        },
    )
    second = client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/example-course/lesson/a2/second-lesson",
            "mode": "normal",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["course_index"] == 1
    assert second.json()["course_index"] == 2
    listed = client.get("/api/items").json()
    assert [item["course_index"] for item in listed] == [1, 2]


def test_import_course_package_saves_finished_course_without_local_artifacts(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post(
        "/api/import",
        json={
            "format": "course-navigator-share",
            "version": 1,
            "message": "请从第三段开始复习。",
            "items": [
                {
                    "id": "abc123",
                    "source_url": "https://example.com/shared-course",
                    "title": "Shared lesson",
                    "collection_title": "Shared collection",
                    "course_index": 3,
                    "sort_order": 3,
                    "duration": 12,
                    "transcript": [
                        {"start": 0, "end": 2, "text": "Corrected opening."},
                        {"start": 2, "end": 5, "text": "Corrected detail."},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    imported = payload["items"][0]
    assert payload["message"] == "请从第三段开始复习。"
    assert imported["id"] == "abc123-imported"
    assert imported["title"] == "Shared lesson"
    assert imported["custom_title"] is True
    assert imported["collection_title"] == "Shared collection"
    assert imported["course_index"] == 3
    assert imported["transcript_source"] == "imported"
    assert imported["transcript"][0]["text"] == "Corrected opening."
    assert imported["local_video_path"] is None
    assert client.get("/api/items/abc123-imported").json()["transcript"][1]["text"] == "Corrected detail."
    assert not (tmp_path / "subtitles" / "abc123-imported").exists()
    assert not (tmp_path / "downloads").exists()


def test_import_course_package_writes_course_record_to_workspace_only(tmp_path):
    process_dir = tmp_path / "process-data"
    workspace_dir = tmp_path / "course-workspace"
    client = make_client(
        process_dir,
        settings=Settings(data_dir=process_dir, workspace_dir=workspace_dir),
    )

    response = client.post(
        "/api/import",
        json={
            "format": "course-navigator-share",
            "version": 1,
            "items": [
                {
                    "id": "shared-course",
                    "source_url": "https://example.com/shared-course",
                    "title": "Shared lesson",
                    "duration": 12,
                    "transcript": [{"start": 0, "end": 2, "text": "Corrected opening."}],
                    "local_video_path": "downloads/should-not-be-imported.mp4",
                }
            ],
        },
    )

    assert response.status_code == 200
    imported = response.json()["items"][0]
    assert imported["id"] == "shared-course"
    assert imported["local_video_path"] is None
    assert (workspace_dir / "items" / "shared-course.json").exists()
    assert not (process_dir / "items" / "shared-course.json").exists()
    assert not (workspace_dir / "downloads").exists()
    assert not (workspace_dir / "subtitles").exists()
    assert not (process_dir / "subtitles").exists()


def test_imported_course_can_cache_video_after_reusing_deleted_id(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    assert client.delete("/api/items/abc123").status_code == 200

    imported = client.post(
        "/api/import",
        json={
            "format": "course-navigator-share",
            "version": 1,
            "items": [
                {
                    "id": "abc123",
                    "source_url": "https://www.youtube.com/watch?v=abc123",
                    "title": "Imported lesson",
                    "transcript": [{"start": 0, "end": 2, "text": "Corrected opening."}],
                }
            ],
        },
    )
    assert imported.status_code == 200
    assert imported.json()["items"][0]["id"] == "abc123"

    response = client.post(
        "/api/items/abc123/download-jobs",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    assert client.get("/api/items/abc123").json()["local_video_path"].endswith("abc123.mp4")


def test_workspace_keeps_course_records_and_downloads_separate_from_process_files(tmp_path):
    process_dir = tmp_path / "process-data"
    workspace_dir = tmp_path / "course-workspace"
    captured = {}

    class WorkspaceRunner(FakeRunner):
        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            captured["subtitle_dir"] = target_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "abc123.en.vtt").write_text("WEBVTT", encoding="utf-8")
            return super().extract_subtitles(request, target_dir, metadata)

    client = make_client(
        process_dir,
        runner=WorkspaceRunner(),
        settings=Settings(data_dir=process_dir, workspace_dir=workspace_dir),
    )

    extract_response = client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    download_response = client.post(
        "/api/items/abc123/download",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    assert extract_response.status_code == 200
    assert download_response.status_code == 200
    assert captured["subtitle_dir"].resolve().is_relative_to((process_dir / "subtitles").resolve())
    assert (workspace_dir / "items" / "abc123.json").exists()
    assert not (process_dir / "items" / "abc123.json").exists()
    assert (workspace_dir / "downloads" / "abc123.mp4").exists()
    assert not (process_dir / "downloads" / "abc123.mp4").exists()
    assert client.get("/api/items/abc123").json()["local_video_path"] == "downloads/abc123.mp4"
    assert client.get("/api/items/abc123/video").content == b"video"


def test_workspace_copies_legacy_course_records_and_downloads_once(tmp_path):
    legacy_dir = tmp_path / "legacy-data"
    workspace_dir = tmp_path / "course-workspace"
    legacy_library = CourseLibrary(legacy_dir)
    legacy_library.save(
        CourseItem(
            id="abc123",
            source_url="https://example.com/video",
            title="Legacy lesson",
            created_at="2026-05-03T00:00:00Z",
            transcript=[TranscriptSegment(start=0, end=2, text="Hello")],
            local_video_path=legacy_dir / "downloads" / "abc123.mp4",
        )
    )
    (legacy_dir / "downloads").mkdir(parents=True, exist_ok=True)
    (legacy_dir / "downloads" / "abc123.mp4").write_text("video", encoding="utf-8")
    (legacy_dir / "subtitles" / "abc123").mkdir(parents=True, exist_ok=True)
    (legacy_dir / "subtitles" / "abc123" / "abc123.en.vtt").write_text("WEBVTT", encoding="utf-8")

    client = make_client(
        legacy_dir,
        settings=Settings(data_dir=legacy_dir, workspace_dir=workspace_dir),
    )

    response = client.get("/api/items")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "abc123"
    assert response.json()[0]["local_video_path"] == "downloads/abc123.mp4"
    assert (workspace_dir / "items" / "abc123.json").exists()
    assert (workspace_dir / "downloads" / "abc123.mp4").exists()
    assert not (workspace_dir / "subtitles").exists()
    assert client.get("/api/items/abc123/video").content == b"video"


def test_youtube_url_keeps_extractor_title_instead_of_guessing_from_url(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Sample Lesson"


def test_course_title_can_be_renamed_and_is_preserved_on_refresh(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/ai-prompting-for-everyone/lesson/53ttu2p0/pretrained-knowledge",
            "mode": "normal",
        },
    )

    rename_response = client.patch("/api/items/abc123", json={"title": "我自己的标题"})

    assert rename_response.status_code == 200
    assert rename_response.json()["title"] == "我自己的标题"
    assert rename_response.json()["custom_title"] is True

    refreshed = client.post(
        "/api/preview",
        json={
            "url": "https://learn.deeplearning.ai/courses/ai-prompting-for-everyone/lesson/53ttu2p0/pretrained-knowledge",
            "mode": "normal",
        },
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["title"] == "我自己的标题"


def test_course_translated_title_can_be_edited_and_cleared_with_title_change(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    client.post("/api/items/abc123/study", json={"output_language": "zh-CN"})

    translated = client.patch(
        "/api/items/abc123",
        json={"translated_title": "旧标题译文"},
    )

    assert translated.status_code == 200
    assert translated.json()["study"]["translated_title"] == "旧标题译文"

    renamed = client.patch(
        "/api/items/abc123",
        json={"title": "New source title"},
    )

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "New source title"
    assert renamed.json()["study"]["translated_title"] is None


def test_course_title_and_translated_title_can_be_saved_together(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    updated = client.patch(
        "/api/items/abc123",
        json={"title": "Web search", "translated_title": "网络搜索"},
    )

    assert updated.status_code == 200
    assert updated.json()["title"] == "Web search"
    assert updated.json()["study"]["translated_title"] == "网络搜索"


def test_course_collection_and_index_can_be_edited_and_cleared(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/ai-prompting-for-everyone/lesson/53ttu2p0/pretrained-knowledge",
            "mode": "normal",
        },
    )

    updated = client.patch(
        "/api/items/abc123",
        json={
            "collection_title": "提示工程入门",
            "course_index": 2,
            "sort_order": 2,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["collection_title"] == "提示工程入门"
    assert updated.json()["course_index"] == 2

    cleared = client.patch(
        "/api/items/abc123",
        json={
            "collection_title": None,
            "course_index": None,
            "sort_order": None,
        },
    )

    assert cleared.status_code == 200
    assert cleared.json()["collection_title"] == ""
    assert cleared.json()["course_index"] is None


def test_extract_route_uses_transcript_duration_when_metadata_has_none(tmp_path):
    class NoDurationRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.duration = None
            return metadata

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            return [
                TranscriptSegment(start=0, end=12, text="Opening idea."),
                TranscriptSegment(start=12, end=98.5, text="Closing idea."),
            ]

    client = make_client(tmp_path, runner=NoDurationRunner())

    response = client.post(
        "/api/extract",
        json={"url": "https://learn.deeplearning.ai/courses/example", "mode": "normal"},
    )

    assert response.status_code == 200
    assert response.json()["duration"] == 98.5

    list_response = client.get("/api/items")
    assert list_response.json()[0]["duration"] == 98.5


def test_preview_route_saves_metadata_without_extracting_subtitles(tmp_path):
    class PreviewRunner(FakeRunner):
        extract_called = False

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            self.extract_called = True
            return super().extract_subtitles(request, target_dir, metadata)

    runner = PreviewRunner()
    client = make_client(tmp_path, runner=runner)

    response = client.post(
        "/api/preview",
        json={"url": "https://learn.deeplearning.ai/courses/example", "mode": "normal"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "abc123"
    assert payload["metadata"]["stream_url"] == "https://cdn.example.com/sample.m3u8"
    assert payload["transcript"] == []
    assert runner.extract_called is False


def test_preview_route_preserves_existing_transcript_and_cache(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    client.post(
        "/api/items/abc123/download",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post(
        "/api/preview",
        json={"url": "https://www.youtube.com/watch?v=abc123&t=13s", "mode": "normal"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcript"][0]["text"] == "Opening idea."
    assert payload["local_video_path"].endswith("abc123.mp4")


def test_extract_route_saves_item_when_subtitles_are_unavailable(tmp_path):
    class NoSubtitleRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            return metadata.model_copy(update={"subtitles": [], "automatic_captions": []})

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            raise YtDlpError("yt-dlp did not produce a subtitle file")

    client = make_client(tmp_path, runner=NoSubtitleRunner())

    response = client.post(
        "/api/extract",
        json={"url": "https://learn.deeplearning.ai/courses/example", "mode": "normal"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "abc123"
    assert payload["transcript"] == []
    assert payload["metadata"]["stream_url"] == "https://cdn.example.com/sample.m3u8"


def test_extract_route_falls_back_to_asr_when_subtitles_are_unavailable(tmp_path):
    class AsrFallbackRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            return metadata.model_copy(update={"subtitles": [], "automatic_captions": []})

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            raise YtDlpError("yt-dlp did not produce a subtitle file")

        def extract_asr(self, request, target_dir: Path, item_id: str):
            return [TranscriptSegment(start=0, end=3, text="ASR transcript line.")]

    client = make_client(tmp_path, runner=AsrFallbackRunner())

    response = client.post(
        "/api/extract",
        json={"url": "https://learn.deeplearning.ai/courses/example", "mode": "normal"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcript_source"] == "asr"
    assert payload["transcript"][0]["text"] == "ASR transcript line."


def test_extract_route_does_not_fall_back_to_asr_when_source_subtitles_are_advertised(tmp_path):
    class AdvertisedSubtitleRunner(FakeRunner):
        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            raise YtDlpError("yt-dlp did not produce a subtitle file")

        def extract_asr(self, request, target_dir: Path, item_id: str):
            raise AssertionError("ASR fallback should not run when source subtitles are advertised")

    client = make_client(tmp_path, runner=AdvertisedSubtitleRunner())

    response = client.post(
        "/api/extract",
        json={"url": "https://www.bilibili.com/video/BVabc/", "mode": "normal"},
    )

    assert response.status_code == 400
    assert "站方字幕存在" in response.json()["detail"]


def test_extract_route_can_force_asr_source(tmp_path):
    class ForceAsrRunner(FakeRunner):
        subtitle_called = False

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            self.subtitle_called = True
            raise AssertionError("subtitle extraction should not run when ASR is forced")

        def extract_asr(self, request, target_dir: Path, item_id: str):
            return [TranscriptSegment(start=0, end=3, text="Forced ASR line.")]

    runner = ForceAsrRunner()
    client = make_client(tmp_path, runner=runner)

    response = client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/example",
            "mode": "normal",
            "subtitle_source": "asr",
        },
    )

    assert response.status_code == 200
    assert runner.subtitle_called is False
    assert response.json()["transcript_source"] == "asr"
    assert response.json()["transcript"][0]["text"] == "Forced ASR line."


def test_extract_route_auto_cleans_asr_audio_when_cache_exceeds_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "ASR_CACHE_AUTO_CLEANUP_THRESHOLD_BYTES", 5, raising=False)

    class AudioProducingAsrRunner(FakeRunner):
        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            raise AssertionError("subtitle extraction should not run when ASR is forced")

        def extract_asr(self, request, target_dir: Path, item_id: str):
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / f"{item_id}.wav").write_bytes(b"123456")
            return [TranscriptSegment(start=0, end=3, text="Forced ASR line.")]

    client = make_client(tmp_path, runner=AudioProducingAsrRunner())

    response = client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/example",
            "mode": "normal",
            "subtitle_source": "asr",
        },
    )

    assert response.status_code == 200
    assert response.json()["transcript_source"] == "asr"
    assert not (tmp_path / "subtitles" / "abc123" / "abc123.wav").exists()


def test_extract_route_keeps_asr_audio_when_auto_cleanup_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "ASR_CACHE_AUTO_CLEANUP_THRESHOLD_BYTES", 5, raising=False)

    class AudioProducingAsrRunner(FakeRunner):
        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            raise AssertionError("subtitle extraction should not run when ASR is forced")

        def extract_asr(self, request, target_dir: Path, item_id: str):
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / f"{item_id}.wav").write_bytes(b"123456")
            return [TranscriptSegment(start=0, end=3, text="Forced ASR line.")]

    client = make_client(
        tmp_path,
        runner=AudioProducingAsrRunner(),
        settings=Settings(data_dir=tmp_path, asr_cache_auto_cleanup_enabled=False),
    )

    response = client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/example",
            "mode": "normal",
            "subtitle_source": "asr",
        },
    )

    assert response.status_code == 200
    assert response.json()["transcript_source"] == "asr"
    assert (tmp_path / "subtitles" / "abc123" / "abc123.wav").exists()
    assert client.get("/api/settings/asr-cache").json()["size_bytes"] == 6


def test_extract_job_can_force_asr_source_with_progress(tmp_path):
    class ForceAsrRunner(FakeRunner):
        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            raise AssertionError("subtitle extraction should not run when ASR is forced")

        def extract_asr(self, request, target_dir: Path, item_id: str, progress=None):
            if progress:
                progress(55, "正在本地 ASR 转写音频")
            sleep(0.03)
            return [TranscriptSegment(start=0, end=3, text="Forced ASR line.")]

    client = make_client(tmp_path, runner=ForceAsrRunner())

    response = client.post(
        "/api/extract-jobs",
        json={
            "url": "https://learn.deeplearning.ai/courses/example",
            "mode": "normal",
            "subtitle_source": "asr",
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    assert payload["item_id"] == "abc123"
    item = client.get("/api/items/abc123").json()
    assert item["transcript_source"] == "asr"
    assert item["transcript"][0]["text"] == "Forced ASR line."


def test_extract_route_can_force_online_asr_source(tmp_path, monkeypatch):
    class OnlineAsrRunner(FakeRunner):
        subtitle_called = False

        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.language = "en"
            return metadata

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            self.subtitle_called = True
            raise AssertionError("subtitle extraction should not run when online ASR is forced")

    captured = {}

    def fake_online_asr(request, target_dir, item_id, yt_dlp_binary, settings):
        captured["provider"] = settings.provider
        captured["binary"] = yt_dlp_binary
        captured["item_id"] = item_id
        captured["language"] = request.language
        return [TranscriptSegment(start=0, end=2.5, text="Online ASR line.")]

    monkeypatch.setattr("course_navigator.app.extract_online_asr_transcript", fake_online_asr)
    runner = OnlineAsrRunner()
    client = make_client(
        tmp_path,
        runner=runner,
        settings=Settings(
            data_dir=tmp_path,
            online_asr=OnlineAsrSettings(
                provider="xai",
                xai={"api_key": "xai-test"},
            ),
        ),
    )

    response = client.post(
        "/api/extract",
        json={
            "url": "https://learn.deeplearning.ai/courses/example",
            "mode": "normal",
            "subtitle_source": "online_asr",
        },
    )

    assert response.status_code == 200
    assert runner.subtitle_called is False
    assert response.json()["transcript_source"] == "online_asr"
    assert response.json()["transcript"][0]["text"] == "Online ASR line."
    assert captured == {"provider": "xai", "binary": "yt-dlp", "item_id": "abc123", "language": "en"}


def test_extract_uses_safe_id_for_subtitle_directory(tmp_path):
    class OddIdRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.id = "../odd/id"
            return metadata

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            assert target_dir.resolve().is_relative_to((tmp_path / "subtitles").resolve())
            assert ".." not in target_dir.parts
            return super().extract_subtitles(request, target_dir, metadata)

    client = make_client(tmp_path, runner=OddIdRunner())

    response = client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "---odd-id"


def test_generate_study_route_updates_item(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/study")

    assert response.status_code == 200
    assert "Sample Lesson" in response.json()["one_line"]

    item_response = client.get("/api/items/abc123")
    assert item_response.json()["study"]["high_fidelity_text"]


def test_generate_study_route_passes_saved_metadata_to_ai(tmp_path, monkeypatch):
    captured = {}

    def fake_generate_study_material(**kwargs):
        captured["metadata"] = kwargs["metadata"]
        return StudyMaterial(
            one_line="学习地图。",
            time_map=[],
            outline=[],
            detailed_notes="解读",
            high_fidelity_text="详解",
        )

    monkeypatch.setattr("course_navigator.app.generate_study_material", fake_generate_study_material)
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/study", json={"output_language": "zh-CN"})

    assert response.status_code == 200
    assert captured["metadata"].uploader == "Sample Teacher"
    assert captured["metadata"].description == "A course summary mentioning D-tail terminology."


def test_generate_study_route_uses_request_detail_level(tmp_path, monkeypatch):
    captured = {}

    def fake_generate_study_material(**kwargs):
        captured["detail_level"] = kwargs["detail_level"]
        return StudyMaterial(
            one_line="学习地图。",
            time_map=[],
            outline=[],
            detailed_notes="解读",
            high_fidelity_text="详解",
        )

    monkeypatch.setattr("course_navigator.app.generate_study_material", fake_generate_study_material)
    client = make_client(tmp_path, settings=Settings(data_dir=tmp_path, study_detail_level="faithful"))
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/study", json={"output_language": "zh-CN", "detail_level": "standard"})

    assert response.status_code == 200
    assert captured["detail_level"] == "standard"


def test_study_job_passes_saved_metadata_to_ai(tmp_path, monkeypatch):
    captured = {}

    def fake_generate_study_material(**kwargs):
        captured["metadata"] = kwargs["metadata"]
        return StudyMaterial(
            one_line="学习地图。",
            time_map=[],
            outline=[],
            detailed_notes="解读",
            high_fidelity_text="详解",
        )

    monkeypatch.setattr("course_navigator.app.generate_study_material", fake_generate_study_material)
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN"})
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    assert captured["metadata"].uploader == "Sample Teacher"
    assert captured["metadata"].description == "A course summary mentioning D-tail terminology."


def test_study_job_uses_request_detail_level(tmp_path, monkeypatch):
    captured = {}

    def fake_generate_study_material(**kwargs):
        captured["detail_level"] = kwargs["detail_level"]
        return StudyMaterial(
            one_line="学习地图。",
            time_map=[],
            outline=[],
            detailed_notes="解读",
            high_fidelity_text="详解",
        )

    monkeypatch.setattr("course_navigator.app.generate_study_material", fake_generate_study_material)
    client = make_client(tmp_path, settings=Settings(data_dir=tmp_path, study_detail_level="faithful"))
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN", "detail_level": "standard"})
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    assert captured["detail_level"] == "standard"


def test_generate_study_route_accepts_chinese_output_language(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/study", json={"output_language": "zh-CN"})

    assert response.status_code == 200
    assert "包含" in response.json()["one_line"]


def test_study_job_generates_in_background(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN"})

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    assert payload["progress"] == 100
    item_response = client.get("/api/items/abc123")
    assert item_response.json()["study"]["high_fidelity_text"]


def test_study_job_saves_partial_study_sections_before_completion(tmp_path, monkeypatch):
    def fake_generate(**kwargs):
        kwargs["partial_study"](
            StudyMaterial(
                one_line="先出的导览。",
                time_map=[],
                outline=[],
                detailed_notes="",
                high_fidelity_text="",
                prerequisites=["先出的预备知识"],
            )
        )
        sleep(0.08)
        return StudyMaterial(
            one_line="最终学习地图。",
            time_map=[],
            outline=[],
            detailed_notes="最终解读",
            high_fidelity_text="最终详解",
        )

    monkeypatch.setattr("course_navigator.app.generate_study_material", fake_generate)
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN"})
    job_id = response.json()["job_id"]
    partial_seen = False
    for _ in range(20):
        item_response = client.get("/api/items/abc123")
        study = item_response.json()["study"]
        if study and study["prerequisites"] == ["先出的预备知识"]:
            partial_seen = True
            break
        sleep(0.01)

    assert partial_seen

    payload = client.get(f"/api/jobs/{job_id}").json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    assert client.get("/api/items/abc123").json()["study"]["high_fidelity_text"] == "最终详解"


def test_translation_job_writes_translated_transcript(tmp_path, monkeypatch):
    captured = {}

    def fake_translate(**kwargs):
        captured["metadata"] = kwargs["metadata"]
        translated = [
            TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {segment.text}")
            for segment in kwargs["transcript"]
        ]
        kwargs["context_summary_created"]("翻译阶段上下文摘要")
        kwargs["title_translation"]("示例课程")
        kwargs["partial_translation"](translated[:1])
        return translated

    monkeypatch.setattr("course_navigator.app.translate_transcript_material", fake_translate)
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    item = CourseLibrary(tmp_path).get("abc123")
    assert item is not None
    item.study = StudyMaterial(
        one_line="已有导览",
        time_map=[],
        outline=[],
        detailed_notes="已有解读",
        high_fidelity_text="已有详解",
        beginner_focus=["已有初学建议"],
        experienced_guidance=["已有进阶建议"],
    )
    CourseLibrary(tmp_path).save(item)

    response = client.post("/api/items/abc123/translation-jobs", json={"output_language": "zh-CN"})

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    item_response = client.get("/api/items/abc123")
    translated = item_response.json()["study"]["translated_transcript"]
    assert translated[0]["text"] == "译文 Opening idea."
    assert item_response.json()["study"]["translated_title"] == "示例课程"
    assert item_response.json()["study"]["context_summary"] == "翻译阶段上下文摘要"
    assert item_response.json()["study"]["beginner_focus"] == ["已有初学建议"]
    assert item_response.json()["study"]["experienced_guidance"] == ["已有进阶建议"]
    assert captured["metadata"].uploader == "Sample Teacher"
    assert captured["metadata"].description == "A course summary mentioning D-tail terminology."


def test_incomplete_cached_translation_is_hidden_from_response(tmp_path, monkeypatch):
    def fake_translate(**kwargs):
        return [
            TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
            for segment in kwargs["transcript"]
        ]

    monkeypatch.setattr("course_navigator.app.translate_transcript_material", fake_translate)
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post("/api/items/abc123/translation-jobs", json={"output_language": "zh-CN"})
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    item_response = client.get("/api/items/abc123")
    assert item_response.json()["study"]["translated_transcript"] == []


def test_transcript_update_saves_corrected_source_and_clears_cached_translation(tmp_path, monkeypatch):
    def fake_translate(**kwargs):
        return [
            TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {segment.text}")
            for segment in kwargs["transcript"]
        ]

    monkeypatch.setattr("course_navigator.app.translate_transcript_material", fake_translate)
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    response = client.post("/api/items/abc123/translation-jobs", json={"output_language": "zh-CN"})
    job_id = response.json()["job_id"]
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    updated = client.put(
        "/api/items/abc123/transcript",
        json={
            "transcript": [
                {"start": 0, "end": 4, "text": "Opening idea corrected."},
                {"start": 4, "end": 8, "text": "Important detail."},
            ]
        },
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["transcript"][0]["text"] == "Opening idea corrected."
    assert payload["study"]["translated_transcript"] == []


def test_study_generation_uses_saved_corrected_transcript(tmp_path, monkeypatch):
    captured = {}

    def fake_generate_study_material(**kwargs):
        captured["transcript"] = kwargs["transcript"]
        return StudyMaterial(
            one_line="已使用校正字幕生成学习地图。",
            time_map=[],
            outline=[],
            detailed_notes="",
            high_fidelity_text="",
        )

    monkeypatch.setattr("course_navigator.app.generate_study_material", fake_generate_study_material)
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    client.put(
        "/api/items/abc123/transcript",
        json={
            "transcript": [
                {"start": 0, "end": 4, "text": "Opening idea corrected."},
                {"start": 4, "end": 8, "text": "Important detail corrected."},
            ]
        },
    )

    response = client.post("/api/items/abc123/study", json={"output_language": "zh-CN"})

    assert response.status_code == 200
    assert captured["transcript"][0].text == "Opening idea corrected."
    assert captured["transcript"][1].text == "Important detail corrected."


def test_asr_correction_job_uses_selected_profile_and_exposes_suggestions(tmp_path, monkeypatch):
    captured = {}

    def fake_suggest(**kwargs):
        captured["provider_model"] = kwargs["provider"].model
        captured["search_enabled"] = kwargs["search_config"].enabled
        captured["transcript"] = kwargs["transcript"]
        captured["context"] = kwargs["context"]
        captured["output_language"] = kwargs["output_language"]
        return [
            {
                "segment_index": 1,
                "original_text": "Important detail.",
                "corrected_text": "Important D-tail.",
                "confidence": 0.91,
                "reason": "课程上下文里该术语是 D-tail。",
                "evidence": "模型根据相邻字幕判断。",
                "source": "model",
            }
        ]

    monkeypatch.setattr("course_navigator.app.suggest_asr_corrections", fake_suggest)
    client = make_client(
        tmp_path,
        settings=Settings(
            data_dir=tmp_path,
            model_profiles=[
                {
                    "id": "translation",
                    "name": "Translation",
                    "base_url": "https://api.example.com/v1",
                    "model": "fast-model",
                    "api_key": "sk-fast",
                },
                {
                    "id": "asr",
                    "name": "ASR",
                    "base_url": "https://api.example.com/v1",
                    "model": "careful-asr-model",
                    "api_key": "sk-asr",
                },
            ],
            translation_model_id="translation",
            learning_model_id="translation",
            global_model_id="translation",
            asr_model_id="asr",
        ),
    )
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post(
        "/api/items/abc123/asr-correction-jobs",
        json={
            "user_context": "NovaDeck 常被误转为 noba dek；VectorRay 常被误转为 vector ray。",
            "output_language": "zh-CN",
            "search": {"enabled": False},
        },
    )

    assert response.status_code == 200
    assert response.json()["started_at"]
    assert response.json()["updated_at"]
    job_id = response.json()["job_id"]
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)
    result = client.get(f"/api/asr-correction-jobs/{job_id}/result")

    assert payload["status"] == "succeeded"
    assert captured["provider_model"] == "careful-asr-model"
    assert captured["search_enabled"] is False
    assert captured["output_language"] == "zh-CN"
    assert captured["transcript"][1].text == "Important detail."
    assert captured["context"]["title"] == "Sample Lesson"
    assert captured["context"]["metadata_title"] == "Sample Lesson"
    assert captured["context"]["uploader"] == "Sample Teacher"
    assert captured["context"]["channel"] == "Sample Channel"
    assert captured["context"]["creator"] == "Sample Creator"
    assert captured["context"]["description"] == "A course summary mentioning D-tail terminology."
    assert captured["context"]["user_context"] == "NovaDeck 常被误转为 noba dek；VectorRay 常被误转为 vector ray。"
    assert captured["context"]["extractor"] == "youtube"
    assert captured["context"]["webpage_url"] == "https://www.youtube.com/watch?v=abc123"
    assert result.status_code == 200
    assert result.json()["suggestions"][0]["corrected_text"] == "Important D-tail."
    assert result.json()["suggestions"][0]["confidence"] == 0.91


def test_asr_correction_job_uses_saved_search_credentials(tmp_path, monkeypatch):
    captured = {}

    def fake_suggest(**kwargs):
        captured["search_config"] = kwargs["search_config"]
        return []

    monkeypatch.setattr("course_navigator.app.suggest_asr_corrections", fake_suggest)
    client = make_client(
        tmp_path,
        settings=Settings(
            data_dir=tmp_path,
            model_profiles=[
                {
                    "id": "asr",
                    "name": "ASR",
                    "base_url": "https://api.example.com/v1",
                    "model": "careful-asr-model",
                    "api_key": "sk-asr",
                }
            ],
            translation_model_id="asr",
            learning_model_id="asr",
            global_model_id="asr",
            asr_model_id="asr",
            asr_search={
                "provider": "firecrawl",
                "result_limit": 7,
                "firecrawl": {"base_url": "http://firecrawl.local:43123", "api_key": "fc-secret"},
            },
        ),
    )
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post(
        "/api/items/abc123/asr-correction-jobs",
        json={"search": {"enabled": True, "provider": "firecrawl", "result_limit": 7}},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)
    assert payload["status"] == "succeeded"
    assert captured["search_config"].base_url == "http://firecrawl.local:43123"
    assert captured["search_config"].api_key == "fc-secret"


def test_model_settings_can_be_read_and_updated(tmp_path):
    env_path = tmp_path / ".env"
    client = make_client(
        tmp_path,
        env_path=env_path,
        settings=Settings(
            data_dir=tmp_path,
            llm_base_url="https://api.primary.example/v1",
            llm_model="provider/Primary-Chat-V2",
            llm_api_key="sk-test-secret-value",
        ),
    )

    initial = client.get("/api/settings/model")

    assert initial.status_code == 200
    assert initial.json()["profiles"][0]["name"] == "Primary Chat V2"
    assert initial.json()["translation_model_id"] == "default"

    updated = client.put(
        "/api/settings/model",
        json={
            "profiles": [
                {
                    "id": "fast",
                    "name": "Fast Model",
                    "provider_type": "openai",
                    "base_url": "https://api.example.com/v1",
                    "model": "fast-chat",
                    "context_window": 64000,
                    "max_tokens": 4096,
                    "api_key": "sk-fast-secret",
                },
                {
                    "id": "long",
                    "name": "Long Model",
                    "provider_type": "anthropic",
                    "base_url": "https://api.example.com/v1",
                    "model": "long-context-chat",
                    "context_window": 1000000,
                    "max_tokens": 32000,
                    "api_key": "sk-long-secret",
                },
            ],
            "translation_model_id": "fast",
            "learning_model_id": "long",
            "global_model_id": "long",
            "asr_model_id": "long",
            "study_detail_level": "detailed",
            "task_parameters": {
                "semantic_segmentation": {"temperature": 0.24, "max_tokens": 9000},
                "high_fidelity": {"temperature": 0.42, "max_tokens": 16000},
                "asr_correction": {"temperature": 0.12, "max_tokens": 12000},
            },
        },
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["translation_model_id"] == "fast"
    assert payload["learning_model_id"] == "long"
    assert payload["global_model_id"] == "long"
    assert payload["asr_model_id"] == "long"
    assert payload["study_detail_level"] == "detailed"
    assert payload["task_parameters"]["semantic_segmentation"] == {"temperature": 0.24, "max_tokens": 9000}
    assert payload["task_parameters"]["high_fidelity"] == {"temperature": 0.42, "max_tokens": 16000}
    assert payload["task_parameters"]["asr_correction"] == {"temperature": 0.12, "max_tokens": 12000}
    assert payload["profiles"][1]["provider_type"] == "anthropic"
    assert payload["profiles"][1]["context_window"] == 1000000
    assert payload["profiles"][1]["max_tokens"] == 32000
    assert payload["profiles"][0]["api_key_preview"] != "sk-fast-secret"
    assert "api_key" not in payload["profiles"][0]
    written = env_path.read_text(encoding="utf-8")
    assert "COURSE_NAVIGATOR_MODEL_PROFILES" in written
    assert "COURSE_NAVIGATOR_TRANSLATION_MODEL_ID" in written
    assert "COURSE_NAVIGATOR_ASR_MODEL_ID" in written
    assert "COURSE_NAVIGATOR_STUDY_DETAIL_LEVEL" in written
    assert "COURSE_NAVIGATOR_TASK_PARAMETERS" in written


def test_create_app_allows_configured_web_origin(tmp_path):
    client = make_client(
        tmp_path,
        settings=Settings(
            data_dir=tmp_path,
            web_host="127.0.0.1",
            web_port=61234,
        ),
    )

    response = client.options(
        "/api/items",
        headers={
            "Origin": "http://127.0.0.1:61234",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:61234"


def test_asr_search_settings_can_be_read_and_updated_without_exposing_keys(tmp_path):
    env_path = tmp_path / ".env"
    client = make_client(
        tmp_path,
        env_path=env_path,
        settings=Settings(
            data_dir=tmp_path,
            asr_search={
                "enabled": True,
                "provider": "tavily",
                "result_limit": 6,
                "tavily": {"base_url": "https://api.tavily.com", "api_key": "tvly-secret-value"},
            },
        ),
    )

    initial = client.get("/api/settings/asr-search")

    assert initial.status_code == 200
    payload = initial.json()
    assert payload["enabled"] is True
    assert payload["provider"] == "tavily"
    assert payload["result_limit"] == 6
    assert payload["tavily"]["has_api_key"] is True
    assert payload["tavily"]["api_key_preview"] != "tvly-secret-value"
    assert "api_key" not in payload["tavily"]

    updated = client.put(
        "/api/settings/asr-search",
        json={
            "enabled": True,
            "provider": "firecrawl",
            "result_limit": 4,
            "firecrawl": {"base_url": "http://127.0.0.1:43123", "api_key": "fc-secret-value"},
        },
    )

    assert updated.status_code == 200
    assert updated.json()["provider"] == "firecrawl"
    assert updated.json()["firecrawl"]["base_url"] == "http://127.0.0.1:43123"
    assert updated.json()["firecrawl"]["has_api_key"] is True
    written = env_path.read_text(encoding="utf-8")
    assert "COURSE_NAVIGATOR_ASR_SEARCH_PROVIDER=\"firecrawl\"" in written
    assert "COURSE_NAVIGATOR_FIRECRAWL_BASE_URL=\"http://127.0.0.1:43123\"" in written


def test_online_asr_settings_can_be_read_and_updated_without_exposing_keys(tmp_path):
    env_path = tmp_path / ".env"
    client = make_client(
        tmp_path,
        env_path=env_path,
        settings=Settings(
            data_dir=tmp_path,
            online_asr=OnlineAsrSettings(
                provider="openai",
                openai={"api_key": "sk-openai-secret"},
                custom={"base_url": "https://asr.example.com/v1", "model": "speech-model", "api_key": "custom-secret"},
            ),
        ),
    )

    initial = client.get("/api/settings/online-asr")

    assert initial.status_code == 200
    payload = initial.json()
    assert payload["provider"] == "openai"
    assert payload["openai"]["has_api_key"] is True
    assert payload["openai"]["api_key_preview"] != "sk-openai-secret"
    assert "api_key" not in payload["openai"]
    assert payload["custom"]["base_url"] == "https://asr.example.com/v1"
    assert payload["custom"]["model"] == "speech-model"

    updated = client.put(
        "/api/settings/online-asr",
        json={
            "provider": "xai",
            "xai": {"api_key": "xai-secret-value"},
            "custom": {"base_url": "https://custom.example.com/audio", "model": "custom-whisper"},
        },
    )

    assert updated.status_code == 200
    assert updated.json()["provider"] == "xai"
    assert updated.json()["xai"]["has_api_key"] is True
    written = env_path.read_text(encoding="utf-8")
    assert "COURSE_NAVIGATOR_ONLINE_ASR_PROVIDER=\"xai\"" in written
    assert "COURSE_NAVIGATOR_XAI_ASR_API_KEY=\"xai-secret-value\"" in written
    assert "COURSE_NAVIGATOR_CUSTOM_ASR_BASE_URL=\"https://custom.example.com/audio\"" in written
    assert "COURSE_NAVIGATOR_CUSTOM_ASR_MODEL=\"custom-whisper\"" in written


def test_online_asr_settings_can_disable_provider(tmp_path):
    env_path = tmp_path / ".env"
    client = make_client(
        tmp_path,
        env_path=env_path,
        settings=Settings(
            data_dir=tmp_path,
            online_asr=OnlineAsrSettings(provider="xai", xai={"api_key": "xai-secret-value"}),
        ),
    )

    updated = client.put("/api/settings/online-asr", json={"provider": "none"})

    assert updated.status_code == 200
    assert updated.json()["provider"] == "none"
    written = env_path.read_text(encoding="utf-8")
    assert "COURSE_NAVIGATOR_ONLINE_ASR_PROVIDER=\"none\"" in written
    assert "COURSE_NAVIGATOR_XAI_ASR_API_KEY=\"xai-secret-value\"" in written


def test_asr_cache_status_reports_audio_cache_and_default_auto_cleanup(tmp_path):
    subtitle_dir = tmp_path / "subtitles" / "abc123"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    (subtitle_dir / "abc123.wav").write_bytes(b"a" * 10)
    (subtitle_dir / "abc123.online-asr.mp3").write_bytes(b"b" * 7)
    (subtitle_dir / "abc123.en.vtt").write_text("WEBVTT", encoding="utf-8")
    client = make_client(tmp_path)

    response = client.get("/api/settings/asr-cache")

    assert response.status_code == 200
    payload = response.json()
    assert payload["size_bytes"] == 17
    assert payload["threshold_bytes"] == 500 * 1024 * 1024
    assert payload["auto_cleanup_enabled"] is True


def test_asr_cache_cleanup_removes_audio_files_but_keeps_subtitle_files(tmp_path):
    subtitle_dir = tmp_path / "subtitles" / "abc123"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    wav_path = subtitle_dir / "abc123.wav"
    mp3_path = subtitle_dir / "abc123.online-asr.mp3"
    vtt_path = subtitle_dir / "abc123.en.vtt"
    wav_path.write_bytes(b"a" * 10)
    mp3_path.write_bytes(b"b" * 7)
    vtt_path.write_text("WEBVTT", encoding="utf-8")
    client = make_client(tmp_path)

    response = client.post("/api/settings/asr-cache/cleanup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cleaned_bytes"] == 17
    assert payload["size_bytes"] == 0
    assert not wav_path.exists()
    assert not mp3_path.exists()
    assert vtt_path.exists()


def test_asr_cache_auto_cleanup_setting_persists_to_env(tmp_path):
    env_path = tmp_path / ".env"
    client = make_client(tmp_path, env_path=env_path)

    response = client.put("/api/settings/asr-cache", json={"auto_cleanup_enabled": False})

    assert response.status_code == 200
    assert response.json()["auto_cleanup_enabled"] is False
    written = env_path.read_text(encoding="utf-8")
    assert "COURSE_NAVIGATOR_ASR_CACHE_AUTO_CLEANUP_ENABLED=\"false\"" in written


def test_model_list_endpoint_uses_saved_profile_key(tmp_path, monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "provider/Primary-Chat-V2"}, {"id": "provider/Reasoner-V1"}]}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("course_navigator.app.httpx.get", fake_get)
    client = make_client(
        tmp_path,
        settings=Settings(
            data_dir=tmp_path,
            model_profiles=[
                {
                    "id": "default",
                    "name": "Primary",
                    "base_url": "https://api.example.com/v1/chat/completions",
                    "model": "provider/Primary-Chat-V2",
                    "api_key": "sk-saved",
                }
            ],
        ),
    )

    response = client.post(
        "/api/settings/models",
        json={
            "provider_type": "openai",
            "base_url": "https://api.example.com/v1/chat/completions",
            "profile_id": "default",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == ["provider/Primary-Chat-V2", "provider/Reasoner-V1"]
    assert captured["url"] == "https://api.example.com/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer sk-saved"


def test_model_list_endpoint_adds_v1_for_anthropic_base(tmp_path, monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "LongContext-M2"}]}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("course_navigator.app.httpx.get", fake_get)
    client = make_client(tmp_path)

    response = client.post(
        "/api/settings/models",
            json={
                "provider_type": "anthropic",
                "base_url": "https://api.anthropic.com",
                "api_key": "sk-request",
            },
        )

    assert response.status_code == 200
    assert response.json()["models"] == ["LongContext-M2"]
    assert captured["url"] == "https://api.anthropic.com/v1/models"
    assert captured["headers"]["x-api-key"] == "sk-request"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"


def test_model_list_endpoint_adds_v1_for_anthropic_path_prefix(tmp_path, monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "mimo-v2.5-pro"}]}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("course_navigator.app.httpx.get", fake_get)
    client = make_client(tmp_path)

    response = client.post(
        "/api/settings/models",
        json={
            "provider_type": "anthropic",
            "base_url": "https://token-plan-cn.xiaomimimo.com/anthropic",
            "api_key": "sk-request",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == ["mimo-v2.5-pro"]
    assert captured["url"] == "https://token-plan-cn.xiaomimimo.com/anthropic/v1/models"


def test_download_route_updates_local_video_path(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post(
        "/api/items/abc123/download",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    assert response.status_code == 200
    assert response.json()["path"].endswith("abc123.mp4")
    item_response = client.get("/api/items/abc123")
    assert item_response.json()["local_video_path"].endswith("abc123.mp4")


def test_download_job_reports_progress_and_updates_local_video_path(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post(
        "/api/items/abc123/download-jobs",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    payload = response.json()
    observed_progress = {payload["progress"]}
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        observed_progress.add(payload["progress"])
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert 42 in observed_progress
    assert payload["status"] == "succeeded"
    assert payload["progress"] == 100
    item_response = client.get("/api/items/abc123")
    assert item_response.json()["local_video_path"].endswith("abc123.mp4")


def test_import_local_video_copies_file_to_workspace_downloads_and_creates_course_item(tmp_path):
    process_dir = tmp_path / "process"
    workspace_dir = tmp_path / "workspace"
    client = make_client(process_dir, runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)

    response = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "Local-Lesson"
    assert payload["title"] == "Local Lesson"
    assert payload["source_url"] == "local-video://Local-Lesson"
    assert payload["duration"] == 67.5
    assert payload["course_index"] == 1
    assert payload["sort_order"] == 1
    assert payload["local_video_path"] == "downloads/Local-Lesson.mp4"
    assert (workspace_dir / "items" / "Local-Lesson.json").exists()
    assert (workspace_dir / "downloads" / "Local-Lesson.mp4").read_bytes() == b"local video"
    assert not (process_dir / "downloads").exists()
    assert client.get("/api/items/Local-Lesson/video").content == b"local video"


def test_existing_empty_workspace_receives_legacy_items_and_downloads(tmp_path):
    legacy_dir = tmp_path / "legacy"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    CourseLibrary(legacy_dir).save(
        CourseItem(
            id="legacy-lesson",
            source_url="https://example.com/lesson",
            title="Legacy Lesson",
            created_at="2026-01-01T00:00:00+00:00",
        )
    )
    legacy_downloads = legacy_dir / "downloads"
    legacy_downloads.mkdir(parents=True)
    (legacy_downloads / "legacy-lesson.mp4").write_bytes(b"video")

    make_client(legacy_dir, workspace_dir=workspace_dir)

    assert (workspace_dir / "items" / "legacy-lesson.json").exists()
    assert (workspace_dir / "downloads" / "legacy-lesson.mp4").read_bytes() == b"video"


def test_startup_backfills_missing_study_guidance_fields(tmp_path):
    workspace_dir = tmp_path / "workspace"
    items_dir = workspace_dir / "items"
    items_dir.mkdir(parents=True)
    item_path = items_dir / "legacy-study.json"
    item_path.write_text(
        json.dumps(
            {
                "id": "legacy-study",
                "source_url": "https://example.com/legacy-study",
                "title": "Legacy Study",
                "created_at": "2026-01-01T00:00:00+00:00",
                "study": {
                    "one_line": "旧导览",
                    "time_map": [],
                    "outline": [],
                    "detailed_notes": "",
                    "high_fidelity_text": "",
                },
            }
        ),
        encoding="utf-8",
    )

    make_client(tmp_path / "process", workspace_dir=workspace_dir)

    payload = json.loads(item_path.read_text(encoding="utf-8"))
    assert payload["study"]["beginner_focus"] == []
    assert payload["study"]["experienced_guidance"] == []


def test_delete_local_video_rejects_local_imports_without_removing_file(tmp_path):
    workspace_dir = tmp_path / "workspace"
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)
    client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    )

    response = client.delete("/api/items/Local-Lesson/local-video")

    assert response.status_code == 400
    assert response.json()["detail"] == "Local video imports must be deleted from the course library"
    assert client.get("/api/items/Local-Lesson").status_code == 200
    assert (workspace_dir / "downloads" / "Local-Lesson.mp4").exists()


def test_delete_local_import_course_removes_imported_video_file(tmp_path):
    workspace_dir = tmp_path / "workspace"
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)
    client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    )

    response = client.delete("/api/items/Local-Lesson")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert client.get("/api/items/Local-Lesson").status_code == 404
    assert not (workspace_dir / "items" / "Local-Lesson.json").exists()
    assert not (workspace_dir / "downloads" / "Local-Lesson.mp4").exists()


def test_import_local_video_assigns_next_index_in_unfiled_collection(tmp_path):
    client = make_client(tmp_path, runner=FakeLocalVideoRunner())
    first = client.post(
        "/api/local-videos",
        files={"file": ("First.mp4", b"first", "video/mp4")},
    ).json()

    second = client.post(
        "/api/local-videos",
        files={"file": ("Second.mp4", b"second", "video/mp4")},
    ).json()

    assert first["course_index"] == 1
    assert second["course_index"] == 2
    assert second["sort_order"] == 2


def test_existing_local_video_backfills_duration_and_course_index(tmp_path):
    workspace_dir = tmp_path / "workspace"
    downloads_dir = workspace_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    (downloads_dir / "existing.mp4").write_bytes(b"video")
    library = CourseLibrary(workspace_dir)
    library.save(
        CourseItem(
            id="existing",
            source_url="local-video://existing",
            title="Existing local video",
            created_at="2026-01-01T00:00:00+00:00",
            duration=None,
            course_index=None,
            sort_order=None,
            local_video_path=Path("downloads/existing.mp4"),
        )
    )
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)

    item = client.get("/api/items/existing").json()

    assert item["duration"] == 67.5
    assert item["course_index"] == 1
    assert item["sort_order"] == 1
    saved = CourseLibrary(workspace_dir).get("existing")
    assert saved.duration == 67.5
    assert saved.course_index == 1


def test_import_local_video_keeps_title_and_uses_safe_id_for_non_ascii_filename(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/local-videos",
        files={"file": ("本地课程.mp4", b"local video", "video/mp4")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "course"
    assert payload["title"] == "本地课程"
    assert payload["local_video_path"] == "downloads/course.mp4"
    assert client.get("/api/items/course/video").content == b"local video"


def test_local_video_extract_job_runs_asr_from_workspace_file(tmp_path):
    client = make_client(tmp_path, runner=FakeLocalVideoRunner())
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    ).json()

    response = client.post(
        "/api/extract-jobs",
        json={
            "url": imported["source_url"],
            "mode": "normal",
            "subtitle_source": "asr",
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    assert payload["item_id"] == "Local-Lesson"
    item = client.get("/api/items/Local-Lesson").json()
    assert item["transcript_source"] == "asr"
    assert item["transcript"][0]["text"] == "Local transcript"


def test_local_video_extract_job_supports_online_asr_from_workspace_file(tmp_path, monkeypatch):
    captured = {}

    def fake_online_asr(request, transcript_dir, item_id, yt_dlp_binary, settings, source_video_path=None, progress=None):
        captured["source_video_path"] = source_video_path
        captured["yt_dlp_binary"] = yt_dlp_binary
        if progress:
            progress(45, "正在请求在线 ASR")
        return [TranscriptSegment(start=0, end=2, text="Online transcript")]

    monkeypatch.setattr(app_module, "extract_online_asr_transcript", fake_online_asr)
    client = make_client(tmp_path, runner=FakeLocalVideoRunner())
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    ).json()

    response = client.post(
        "/api/extract-jobs",
        json={
            "url": imported["source_url"],
            "mode": "normal",
            "subtitle_source": "online_asr",
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "succeeded"
    item = client.get("/api/items/Local-Lesson").json()
    assert item["transcript_source"] == "online_asr"
    assert item["transcript"][0]["text"] == "Online transcript"
    assert captured["source_video_path"].name == "Local-Lesson.mp4"
    assert captured["yt_dlp_binary"] is None


def test_local_video_download_route_rejects_recaching(tmp_path):
    client = make_client(tmp_path, runner=FakeLocalVideoRunner())
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    ).json()

    response = client.post(
        "/api/items/Local-Lesson/download",
        json={"url": imported["source_url"], "mode": "normal"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "本地视频已经在 Workspace 中，无需再次缓存。"


def test_extract_route_preserves_local_cache_when_refreshing_subtitles(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    client.post(
        "/api/items/abc123/download",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    assert response.status_code == 200
    assert response.json()["local_video_path"].endswith("abc123.mp4")


def test_video_route_serves_downloaded_file(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    client.post(
        "/api/items/abc123/download",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.get("/api/items/abc123/video")

    assert response.status_code == 200
    assert response.content == b"video"


def test_delete_item_removes_record_and_artifacts(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    client.post(
        "/api/items/abc123/download",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    subtitle_dir = tmp_path / "subtitles" / "abc123"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    (subtitle_dir / "abc123.en.vtt").write_text("WEBVTT", encoding="utf-8")

    response = client.delete("/api/items/abc123")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert client.get("/api/items/abc123").status_code == 404
    assert not (tmp_path / "items" / "abc123.json").exists()
    assert not list((tmp_path / "downloads").glob("abc123.*"))
    assert not subtitle_dir.exists()


def test_delete_item_removes_stale_download_files_even_without_local_video_path(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    (downloads_dir / "abc123.mp4").write_text("video", encoding="utf-8")
    (downloads_dir / "abc123.f399.mp4").write_text("video part", encoding="utf-8")
    (downloads_dir / "abc1234.mp4").write_text("other video", encoding="utf-8")

    response = client.delete("/api/items/abc123")

    assert response.status_code == 200
    assert not list(downloads_dir.glob("abc123.*"))
    assert (downloads_dir / "abc1234.mp4").exists()


def test_download_job_cleans_file_when_course_is_deleted_during_download(tmp_path):
    class SlowDownloadRunner(FakeRunner):
        def download_video(self, request, target_dir: Path, item_id: str, progress=None):
            target_dir.mkdir(parents=True, exist_ok=True)
            if progress:
                progress(42, "正在缓存视频")
            sleep(0.08)
            path = target_dir / f"{item_id}.mp4"
            path.write_text("video", encoding="utf-8")
            return path

    client = make_client(tmp_path, runner=SlowDownloadRunner())
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    response = client.post(
        "/api/items/abc123/download-jobs",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["progress"] == 42:
            break
        sleep(0.01)

    assert client.delete("/api/items/abc123").status_code == 200
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "failed"
    assert payload["error"] == "Course item was deleted"
    assert not list((tmp_path / "downloads").glob("abc123.*"))


def test_delete_local_video_keeps_course_item(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    client.post(
        "/api/items/abc123/download",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    response = client.delete("/api/items/abc123/local-video")

    assert response.status_code == 200
    assert response.json()["local_video_path"] is None
    assert client.get("/api/items/abc123").status_code == 200
    assert not list((tmp_path / "downloads").glob("abc123.*"))


def make_client(
    tmp_path: Path,
    runner=None,
    env_path: Path | None = None,
    settings: Settings | None = None,
    workspace_dir: Path | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path,
            workspace_dir=workspace_dir,
            runner=runner or FakeRunner(),
            settings=settings or Settings(data_dir=tmp_path, workspace_dir=workspace_dir),
            env_path=env_path,
        )
    )
