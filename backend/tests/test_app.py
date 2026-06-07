import json
import os
from pathlib import Path
from threading import Event
from time import sleep
from datetime import datetime, timezone

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
        assert video_path.suffix == ".mp4"
        return [TranscriptSegment(start=0, end=2, text="Local transcript")]


class CountingMetadataRunner(FakeRunner):
    def __init__(self) -> None:
        self.fetch_count = 0

    def fetch_metadata(self, request):
        self.fetch_count += 1
        return super().fetch_metadata(request)


def test_health_route(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_save_cookie_text_accepts_cookie_header(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/cookies/text",
        json={"text": "Cookie: SID=one; YSC=two"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"].endswith("manual.cookies.txt")
    cookie_file = Path(payload["path"])
    assert cookie_file.exists()
    content = cookie_file.read_text(encoding="utf-8")
    assert ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tone" in content
    assert ".youtube.com\tTRUE\t/\tTRUE\t0\tYSC\ttwo" in content


def test_save_cookie_text_accepts_browser_extension_json(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/cookies/text",
        json={
            "text": json.dumps(
                [
                    {
                        "domain": ".youtube.com",
                        "path": "/",
                        "secure": True,
                        "expirationDate": 1893456000,
                        "name": "SID",
                        "value": "json-value",
                    }
                ]
            )
        },
    )

    assert response.status_code == 200
    content = Path(response.json()["path"]).read_text(encoding="utf-8")
    assert ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tjson-value" in content


def test_save_cookie_text_rejects_unusable_cookie_text(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/cookies/text", json={"text": "not a cookie"})

    assert response.status_code == 400


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


def test_list_items_summary_omits_heavy_mobile_fields(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    item = CourseLibrary(tmp_path).get("abc123")
    assert item is not None
    item.study = StudyMaterial(
        one_line="Short takeaway",
        translated_title="示例课程",
        context_summary="Context shown in compact metadata.",
        time_map=[],
        outline=[],
        detailed_notes="Long notes should stay off the list response.",
        high_fidelity_text="Long high-fidelity text should stay off the list response.",
        translated_transcript=[TranscriptSegment(start=0, end=4, text="译文")],
    )
    CourseLibrary(tmp_path).save(item)

    full_payload = client.get("/api/items").json()[0]
    summary_payload = client.get("/api/items?summary=true").json()[0]

    assert full_payload["transcript"][1]["text"] == "Important detail."
    assert full_payload["study"]["detailed_notes"] == "Long notes should stay off the list response."
    assert summary_payload["transcript"] == []
    assert summary_payload["study"]["translated_title"] == "示例课程"
    assert summary_payload["study"]["context_summary"] == "Context shown in compact metadata."
    assert summary_payload["study"]["time_map"] == []
    assert summary_payload["study"]["outline"] == []
    assert summary_payload["study"]["detailed_notes"] == ""
    assert summary_payload["study"]["high_fidelity_text"] == ""
    assert summary_payload["study"]["translated_transcript"] == []


def test_items_expose_updated_at_for_differential_sync(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )

    full_payload = client.get("/api/items/abc123").json()
    summary_payload = client.get("/api/items?summary=true").json()[0]

    assert full_payload["updated_at"]
    assert summary_payload["updated_at"] == full_payload["updated_at"]

    sleep(0.01)
    renamed = client.patch("/api/items/abc123", json={"title": "Renamed lesson"}).json()
    refreshed_summary = client.get("/api/items?summary=true").json()[0]

    assert renamed["updated_at"] != full_payload["updated_at"]
    assert refreshed_summary["updated_at"] == renamed["updated_at"]


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
                    "collection_group_title": "Shared group",
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
    assert imported["collection_group_title"] == "Shared group"
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


def test_imported_course_can_bind_external_video_source_without_losing_artifacts(tmp_path):
    process_dir = tmp_path / "process-data"
    workspace_dir = tmp_path / "course-workspace"
    nas_video = tmp_path / "nas" / "Shared Lesson.mp4"
    nas_video.parent.mkdir()
    nas_video.write_text("video", encoding="utf-8")
    client = make_client(process_dir, runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)

    imported = client.post(
        "/api/import",
        json={
            "format": "course-navigator-share",
            "version": 1,
            "items": [
                {
                    "id": "shared-course",
                    "source_url": "local-video://original-shared-course",
                    "title": "Shared lesson",
                    "duration": 12,
                    "transcript": [{"start": 0, "end": 2, "text": "Corrected opening."}],
                    "study": {
                        "one_line": "已有导览",
                        "time_map": [],
                        "outline": [],
                        "detailed_notes": "已有解读",
                        "high_fidelity_text": "已有详解",
                    },
                }
            ],
        },
    )
    assert imported.status_code == 200
    assert imported.json()["items"][0]["local_video_path"] is None

    response = client.post(
        "/api/items/shared-course/video-source",
        json={"source_type": "external", "path": str(nas_video)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "shared-course"
    assert payload["source_url"] == "external-video://shared-course"
    assert payload["video_source_type"] == "external"
    assert payload["local_video_path"] == str(nas_video.resolve())
    assert payload["duration"] == 67.5
    assert payload["transcript"][0]["text"] == "Corrected opening."
    assert payload["study"]["high_fidelity_text"] == "已有详解"
    assert not (workspace_dir / "downloads").exists()


def test_external_video_course_can_change_to_another_external_video_source(tmp_path):
    workspace_dir = tmp_path / "workspace"
    old_video = tmp_path / "nas" / "Old.mp4"
    new_video = tmp_path / "nas" / "New.mp4"
    old_video.parent.mkdir()
    old_video.write_text("old video", encoding="utf-8")
    new_video.write_text("new video", encoding="utf-8")
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)

    imported = client.post("/api/local-video-paths", json={"paths": [str(old_video)], "mode": "external"})
    item_id = imported.json()[0]["id"]

    response = client.post(
        f"/api/items/{item_id}/video-source",
        json={"source_type": "external", "path": str(new_video)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == item_id
    assert payload["video_source_type"] == "external"
    assert payload["local_video_path"] == str(new_video.resolve())
    assert old_video.exists()
    assert new_video.exists()
    assert not (workspace_dir / "downloads").exists()


def test_external_video_course_can_change_to_remote_video_source(tmp_path):
    old_video = tmp_path / "nas" / "Old.mp4"
    old_video.parent.mkdir()
    old_video.write_text("old video", encoding="utf-8")
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=tmp_path / "workspace")
    imported = client.post("/api/local-video-paths", json={"paths": [str(old_video)], "mode": "external"})
    item_id = imported.json()[0]["id"]

    response = client.post(
        f"/api/items/{item_id}/video-source",
        json={"source_type": "remote", "url": "https://example.com/new-video"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_url"] == "https://example.com/new-video"
    assert payload["video_source_type"] == "remote"
    assert payload["local_video_path"] is None
    assert old_video.exists()


def test_workspace_video_course_cannot_change_video_source_directly(tmp_path):
    workspace_dir = tmp_path / "workspace"
    replacement = tmp_path / "nas" / "Replacement.mp4"
    replacement.parent.mkdir()
    replacement.write_text("replacement", encoding="utf-8")
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    )
    item_id = imported.json()["id"]

    response = client.post(
        f"/api/items/{item_id}/video-source",
        json={"source_type": "external", "path": str(replacement)},
    )

    assert response.status_code == 400
    assert "Workspace" in response.json()["detail"]
    payload = client.get(f"/api/items/{item_id}").json()
    assert payload["source_url"] == f"local-video://{item_id}"
    assert payload["video_source_type"] == "workspace"
    assert payload["local_video_path"].endswith(f"{item_id}.mp4")


def test_missing_workspace_video_file_can_bind_replacement_source(tmp_path):
    workspace_dir = tmp_path / "workspace"
    replacement = tmp_path / "nas" / "Replacement.mp4"
    replacement.parent.mkdir()
    replacement.write_text("replacement", encoding="utf-8")
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    )
    item_id = imported.json()["id"]
    cached_path = workspace_dir / imported.json()["local_video_path"]
    cached_path.unlink()
    missing_video_payload = client.get(f"/api/items/{item_id}").json()

    assert missing_video_payload["local_video_path"] is None
    response = client.post(
        f"/api/items/{item_id}/video-source",
        json={"source_type": "external", "path": str(replacement)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_url"] == f"external-video://{item_id}"
    assert payload["video_source_type"] == "external"
    assert payload["local_video_path"] == str(replacement.resolve())


def test_video_source_picker_binds_single_external_file_to_existing_course(tmp_path, monkeypatch):
    replacement = tmp_path / "nas" / "Replacement.mp4"
    replacement.parent.mkdir()
    replacement.write_text("replacement", encoding="utf-8")
    picker_modes: list[bool] = []
    monkeypatch.setattr(app_module, "_pick_local_video_paths", lambda *, multiple: picker_modes.append(multiple) or [replacement])
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=tmp_path / "workspace")
    imported = client.post(
        "/api/import",
        json={
            "format": "course-navigator-share",
            "version": 1,
            "items": [
                {
                    "id": "shared-course",
                    "source_url": "local-video://shared-course",
                    "title": "Shared course",
                    "created_at": "2026-05-03T00:00:00Z",
                    "transcript": [{"start": 0, "end": 2, "text": "Hello"}],
                    "study": {
                        "one_line": "Existing guide",
                        "translated_title": None,
                        "time_map": [],
                        "outline": [],
                        "detailed_notes": "Existing notes",
                        "high_fidelity_text": "Existing detail",
                        "translated_transcript": [],
                        "prerequisites": [],
                        "thought_prompts": [],
                        "review_suggestions": [],
                    },
                }
            ],
        },
    )
    item_id = imported.json()["items"][0]["id"]

    response = client.post(f"/api/items/{item_id}/video-source-picker")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == item_id
    assert payload["source_url"] == f"external-video://{item_id}"
    assert payload["video_source_type"] == "external"
    assert payload["local_video_path"] == str(replacement.resolve())
    assert payload["transcript"][0]["text"] == "Hello"
    assert client.get("/api/items").json()[0]["id"] == item_id
    assert picker_modes == [False]


def test_workspace_video_picker_imports_single_file_to_existing_course(tmp_path, monkeypatch):
    workspace_dir = tmp_path / "workspace"
    source = tmp_path / "nas" / "Replacement.mp4"
    source.parent.mkdir()
    source.write_text("replacement", encoding="utf-8")
    picker_modes: list[bool] = []
    monkeypatch.setattr(app_module, "_pick_local_video_paths", lambda *, multiple: picker_modes.append(multiple) or [source])
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)
    imported = client.post(
        "/api/import",
        json={
            "format": "course-navigator-share",
            "version": 1,
            "items": [
                {
                    "id": "shared-course",
                    "source_url": "local-video://shared-course",
                    "title": "Shared course",
                    "duration": 12,
                    "created_at": "2026-05-03T00:00:00Z",
                    "transcript": [{"start": 0, "end": 2, "text": "Hello"}],
                    "study": {
                        "one_line": "Existing guide",
                        "translated_title": None,
                        "time_map": [],
                        "outline": [],
                        "detailed_notes": "Existing notes",
                        "high_fidelity_text": "Existing detail",
                        "translated_transcript": [],
                        "prerequisites": [],
                        "thought_prompts": [],
                        "review_suggestions": [],
                    },
                }
            ],
        },
    )
    item_id = imported.json()["items"][0]["id"]

    response = client.post(f"/api/items/{item_id}/workspace-video-picker")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == item_id
    assert payload["source_url"] == f"local-video://{item_id}"
    assert payload["video_source_type"] == "workspace"
    assert payload["local_video_path"] == f"downloads/{item_id}.mp4"
    assert payload["duration"] == 67.5
    assert payload["transcript"][0]["text"] == "Hello"
    assert payload["study"]["high_fidelity_text"] == "Existing detail"
    assert (workspace_dir / payload["local_video_path"]).read_text(encoding="utf-8") == "replacement"
    assert source.exists()
    assert picker_modes == [False]


def test_workspace_video_picker_rejects_existing_workspace_video(tmp_path, monkeypatch):
    source = tmp_path / "nas" / "Replacement.mp4"
    source.parent.mkdir()
    source.write_text("replacement", encoding="utf-8")
    picker_modes: list[bool] = []
    monkeypatch.setattr(app_module, "_pick_local_video_paths", lambda *, multiple: picker_modes.append(multiple) or [source])
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=tmp_path / "workspace")
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    )
    item_id = imported.json()["id"]

    response = client.post(f"/api/items/{item_id}/workspace-video-picker")

    assert response.status_code == 400
    assert "Workspace" in response.json()["detail"]
    assert picker_modes == []


def test_workspace_video_picker_cancel_returns_current_item(tmp_path, monkeypatch):
    picker_modes: list[bool] = []
    monkeypatch.setattr(app_module, "_pick_local_video_paths", lambda *, multiple: picker_modes.append(multiple) or [])
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=tmp_path / "workspace")
    imported = client.post(
        "/api/import",
        json={
            "format": "course-navigator-share",
            "version": 1,
            "items": [
                {
                    "id": "shared-course",
                    "source_url": "local-video://shared-course",
                    "title": "Shared course",
                    "created_at": "2026-05-03T00:00:00Z",
                    "transcript": [{"start": 0, "end": 2, "text": "Hello"}],
                }
            ],
        },
    )
    item_id = imported.json()["items"][0]["id"]

    response = client.post(f"/api/items/{item_id}/workspace-video-picker")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == item_id
    assert payload["local_video_path"] is None
    assert payload["source_url"] == "local-video://shared-course"
    assert picker_modes == [False]


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
            "collection_group_title": "学习",
            "collection_title": "提示工程入门",
            "course_index": 2,
            "sort_order": 2,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["collection_group_title"] == "学习"
    assert updated.json()["collection_title"] == "提示工程入门"
    assert updated.json()["course_index"] == 2

    cleared = client.patch(
        "/api/items/abc123",
        json={
            "collection_group_title": None,
            "collection_title": None,
            "course_index": None,
            "sort_order": None,
        },
    )

    assert cleared.status_code == 200
    assert cleared.json()["collection_group_title"] == ""
    assert cleared.json()["collection_title"] == ""
    assert cleared.json()["course_index"] is None


def test_library_state_is_persisted_and_normalized(tmp_path):
    client = make_client(tmp_path)

    assert client.get("/api/library-state").json() == {
        "manual_collections": [],
        "manual_collection_groups": [],
        "collection_order": [],
        "collection_group_order": [],
        "collection_group_assignments": {},
    }

    updated = client.put(
        "/api/library-state",
        json={
            "manual_collections": [" 摄影 ", "摄影", ""],
            "manual_collection_groups": [" 产品 ", "摄影", "产品"],
            "collection_order": ["collection:a", "collection:a", ""],
            "collection_group_order": ["group:product", "group:photo"],
            "collection_group_assignments": {
                " collection:a ": " 产品 ",
                "collection:b": "",
                "": "摄影",
            },
        },
    )

    assert updated.status_code == 200
    assert updated.json() == {
        "manual_collections": ["摄影"],
        "manual_collection_groups": ["产品", "摄影"],
        "collection_order": ["collection:a"],
        "collection_group_order": ["group:product", "group:photo"],
        "collection_group_assignments": {"collection:a": "产品"},
    }

    reloaded = make_client(tmp_path)
    assert reloaded.get("/api/library-state").json() == updated.json()


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


def test_extract_route_fails_when_subtitles_and_asr_are_unavailable(tmp_path):
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

    assert response.status_code == 400
    assert "站方字幕不可用" in response.json()["detail"]
    assert "字幕兜底失败" in response.json()["detail"]


def test_extract_job_fails_when_source_first_fallback_returns_no_transcript(tmp_path):
    class NoSubtitleRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            return metadata.model_copy(update={"subtitles": [], "automatic_captions": []})

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            raise YtDlpError("yt-dlp did not produce a subtitle file")

    client = make_client(tmp_path, runner=NoSubtitleRunner())

    response = client.post(
        "/api/extract-jobs",
        json={"url": "https://learn.deeplearning.ai/courses/example", "mode": "normal"},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "failed"
    assert "字幕兜底失败" in payload["error"]
    assert client.get("/api/items/abc123").status_code == 404


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


def test_extract_route_source_first_falls_back_to_online_asr_when_configured(tmp_path, monkeypatch):
    class SourceFirstOnlineFallbackRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            return metadata.model_copy(update={"subtitles": [], "automatic_captions": [], "language": "en"})

        def extract_subtitles(self, request, target_dir: Path, metadata=None):
            raise YtDlpError("yt-dlp did not produce a subtitle file")

        def extract_asr(self, request, target_dir: Path, item_id: str):
            raise AssertionError("local ASR should not run before configured online ASR")

    captured = {}

    def fake_online_asr(request, target_dir, item_id, yt_dlp_binary, settings):
        captured["provider"] = settings.provider
        captured["language"] = request.language
        return [TranscriptSegment(start=0, end=3, text="Online fallback line.")]

    monkeypatch.setattr("course_navigator.app.extract_online_asr_transcript", fake_online_asr)
    client = make_client(
        tmp_path,
        runner=SourceFirstOnlineFallbackRunner(),
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
        json={"url": "https://learn.deeplearning.ai/courses/example", "mode": "normal"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcript_source"] == "online_asr"
    assert payload["transcript"][0]["text"] == "Online fallback line."
    assert captured == {"provider": "xai", "language": "en"}


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
    assert captured == {"provider": "xai", "binary": None, "item_id": "abc123", "language": "en"}


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


def test_study_job_section_failure_marks_failed_and_keeps_existing_study(tmp_path, monkeypatch):
    def fail_regenerate(**kwargs):
        raise RuntimeError("high fidelity failed")

    monkeypatch.setattr("course_navigator.app.regenerate_study_section", fail_regenerate)
    client = make_client(tmp_path)
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    library = CourseLibrary(tmp_path)
    item = library.get("abc123")
    assert item is not None
    item.study = StudyMaterial(
        one_line="已有导览",
        time_map=[],
        outline=[],
        detailed_notes="已有解读",
        high_fidelity_text="已有详解",
    )
    library.save(item)

    response = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN", "section": "high"})
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "failed"
    assert payload["error"] == "high fidelity failed"
    assert client.get("/api/items/abc123").json()["study"]["high_fidelity_text"] == "已有详解"


def test_study_job_full_provider_failure_marks_failed_and_keeps_existing_study(tmp_path, monkeypatch):
    def fail_provider_generation(*args, **kwargs):
        raise RuntimeError("learning provider failed")

    monkeypatch.setattr("course_navigator.ai._generate_with_provider", fail_provider_generation)
    client = make_client(
        tmp_path,
        settings=Settings(
            data_dir=tmp_path,
            llm_base_url="https://example.test/v1",
            llm_api_key="sk-test",
            llm_model="test-model",
        ),
    )
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    library = CourseLibrary(tmp_path)
    item = library.get("abc123")
    assert item is not None
    item.study = StudyMaterial(
        one_line="已有导览",
        time_map=[],
        outline=[],
        detailed_notes="已有解读",
        high_fidelity_text="已有详解",
    )
    library.save(item)

    response = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN", "section": "all"})
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "failed"
    assert payload["error"] == "learning provider failed"
    assert client.get("/api/items/abc123").json()["study"]["high_fidelity_text"] == "已有详解"


def test_study_job_full_failure_restores_existing_study_after_partial_save(tmp_path, monkeypatch):
    def fail_after_partial(**kwargs):
        kwargs["partial_study"](
            StudyMaterial(
                one_line="临时导览",
                time_map=[],
                outline=[],
                detailed_notes="临时解读",
                high_fidelity_text="临时详解",
            )
        )
        raise RuntimeError("learning provider failed late")

    monkeypatch.setattr("course_navigator.app.generate_study_material", fail_after_partial)
    client = make_client(
        tmp_path,
        settings=Settings(
            data_dir=tmp_path,
            llm_base_url="https://example.test/v1",
            llm_api_key="sk-test",
            llm_model="test-model",
        ),
    )
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    library = CourseLibrary(tmp_path)
    item = library.get("abc123")
    assert item is not None
    item.study = StudyMaterial(
        one_line="已有导览",
        time_map=[],
        outline=[],
        detailed_notes="已有解读",
        high_fidelity_text="已有详解",
    )
    library.save(item)

    response = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN", "section": "all"})
    job_id = response.json()["job_id"]
    payload = response.json()
    for _ in range(20):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.02)

    assert payload["status"] == "failed"
    assert payload["error"] == "learning provider failed late"
    study = client.get("/api/items/abc123").json()["study"]
    assert study["one_line"] == "已有导览"
    assert study["high_fidelity_text"] == "已有详解"


def test_study_jobs_for_same_course_run_serially_without_old_failure_overwriting_new_success(tmp_path, monkeypatch):
    first_started = Event()
    release_first = Event()
    calls: list[int] = []

    def generate_with_first_failure(**kwargs):
        calls.append(len(calls) + 1)
        if calls[-1] == 1:
            kwargs["partial_study"](
                StudyMaterial(
                    one_line="第一条临时导览",
                    time_map=[],
                    outline=[],
                    detailed_notes="第一条临时解读",
                    high_fidelity_text="第一条临时详解",
                )
            )
            first_started.set()
            assert release_first.wait(2)
            raise RuntimeError("first job failed late")
        return StudyMaterial(
            one_line="第二条成功导览",
            time_map=[],
            outline=[],
            detailed_notes="第二条成功解读",
            high_fidelity_text="第二条成功详解",
        )

    monkeypatch.setattr("course_navigator.app.generate_study_material", generate_with_first_failure)
    client = make_client(
        tmp_path,
        settings=Settings(
            data_dir=tmp_path,
            llm_base_url="https://example.test/v1",
            llm_api_key="sk-test",
            llm_model="test-model",
        ),
    )
    client.post(
        "/api/extract",
        json={"url": "https://www.youtube.com/watch?v=abc123", "mode": "normal"},
    )
    item = CourseLibrary(tmp_path).get("abc123")
    assert item is not None
    item.study = StudyMaterial(
        one_line="原始导览",
        time_map=[],
        outline=[],
        detailed_notes="原始解读",
        high_fidelity_text="原始详解",
    )
    CourseLibrary(tmp_path).save(item)

    first = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN", "section": "all"}).json()
    assert first_started.wait(2)
    second = client.post("/api/items/abc123/study-jobs", json={"output_language": "zh-CN", "section": "all"}).json()
    sleep(0.05)
    assert client.get(f"/api/jobs/{second['job_id']}").json()["status"] == "queued"
    release_first.set()

    payloads = {}
    for job in (first, second):
        payload = job
        for _ in range(50):
            payload = client.get(f"/api/jobs/{job['job_id']}").json()
            if payload["status"] in {"succeeded", "failed"}:
                break
            sleep(0.02)
        payloads[job["job_id"]] = payload

    assert payloads[first["job_id"]]["status"] == "failed"
    assert payloads[second["job_id"]]["status"] == "succeeded"
    study = client.get("/api/items/abc123").json()["study"]
    assert study["one_line"] == "第二条成功导览"
    assert study["high_fidelity_text"] == "第二条成功详解"


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


def test_model_settings_default_env_path_does_not_follow_process_cwd(tmp_path, monkeypatch):
    default_env = app_module.default_env_path()
    original = default_env.read_text(encoding="utf-8") if default_env.exists() else None
    monkeypatch.chdir(tmp_path)
    try:
        client = TestClient(
            create_app(
                data_dir=tmp_path / "data",
                workspace_dir=tmp_path / "workspace",
                runner=FakeRunner(),
                settings=Settings(data_dir=tmp_path / "data", workspace_dir=tmp_path / "workspace"),
            )
        )

        response = client.put(
            "/api/settings/model",
            json={
                "profiles": [
                    {
                        "id": "portable",
                        "name": "Portable Model",
                        "provider_type": "openai",
                        "base_url": "https://api.example.com/v1",
                        "model": "portable-chat",
                        "api_key": "sk-portable-secret",
                    },
                ],
                "translation_model_id": "portable",
                "learning_model_id": "portable",
                "global_model_id": "portable",
                "asr_model_id": "portable",
                "study_detail_level": "faithful",
                "task_parameters": {},
            },
        )

        assert response.status_code == 200
        assert not (tmp_path / ".env").exists()
        assert default_env.exists()
        written = default_env.read_text(encoding="utf-8")
        assert "Portable Model" in written
        assert "COURSE_NAVIGATOR_MODEL_PROFILES" in written
    finally:
        if original is None:
            default_env.unlink(missing_ok=True)
        else:
            default_env.write_text(original, encoding="utf-8")
            os.chmod(default_env, 0o600)


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


def test_import_external_video_paths_links_files_without_copying(tmp_path):
    workspace_dir = tmp_path / "workspace"
    process_dir = tmp_path / "process"
    source_dir = tmp_path / "nas"
    source_dir.mkdir()
    source = source_dir / "NAS Lesson.mp4"
    source.write_bytes(b"external video")
    client = make_client(process_dir, workspace_dir=workspace_dir, runner=FakeLocalVideoRunner())

    response = client.post(
        "/api/local-video-paths",
        json={"paths": [str(source)], "mode": "external"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "NAS-Lesson"
    assert payload[0]["title"] == "NAS Lesson"
    assert payload[0]["source_url"] == "external-video://NAS-Lesson"
    assert payload[0]["video_source_type"] == "external"
    assert Path(payload[0]["local_video_path"]).resolve() == source.resolve()
    assert not (workspace_dir / "downloads" / "NAS-Lesson.mp4").exists()


def test_import_workspace_video_paths_copies_multiple_files(tmp_path):
    workspace_dir = tmp_path / "workspace"
    process_dir = tmp_path / "process"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    first = source_dir / "First.mp4"
    second = source_dir / "Second.webm"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    client = make_client(process_dir, workspace_dir=workspace_dir, runner=FakeLocalVideoRunner())

    response = client.post(
        "/api/local-video-paths",
        json={"paths": [str(first), str(second)], "mode": "workspace"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["First", "Second"]
    assert [item["video_source_type"] for item in payload] == ["workspace", "workspace"]
    assert [item["local_video_path"] for item in payload] == ["downloads/First.mp4", "downloads/Second.webm"]
    assert (workspace_dir / "downloads" / "First.mp4").read_bytes() == b"first"
    assert (workspace_dir / "downloads" / "Second.webm").read_bytes() == b"second"


def test_import_external_video_path_rejects_missing_file(tmp_path):
    client = make_client(tmp_path / "process", workspace_dir=tmp_path / "workspace", runner=FakeLocalVideoRunner())

    response = client.post(
        "/api/local-video-paths",
        json={"paths": [str(tmp_path / "missing.mp4")], "mode": "external"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Local video file not found"


def test_import_external_video_path_rejects_unsupported_file_type(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("not a video", encoding="utf-8")
    client = make_client(tmp_path / "process", workspace_dir=tmp_path / "workspace", runner=FakeLocalVideoRunner())

    response = client.post(
        "/api/local-video-paths",
        json={"paths": [str(source)], "mode": "external"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported local video file type"


def test_local_video_file_picker_imports_selected_paths(tmp_path, monkeypatch):
    source = tmp_path / "NAS Lesson.mp4"
    source.write_bytes(b"external video")
    picker_modes: list[bool] = []
    monkeypatch.setattr(app_module, "_pick_local_video_paths", lambda *, multiple: picker_modes.append(multiple) or [source])
    client = make_client(tmp_path / "process", workspace_dir=tmp_path / "workspace", runner=FakeLocalVideoRunner())

    response = client.post("/api/local-video-file-picker", json={"mode": "external"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["video_source_type"] == "external"
    assert Path(payload[0]["local_video_path"]).resolve() == source.resolve()
    assert picker_modes == [True]


def test_local_video_file_picker_returns_empty_list_when_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "_pick_local_video_paths", lambda *, multiple: [])
    client = make_client(tmp_path / "process", workspace_dir=tmp_path / "workspace", runner=FakeLocalVideoRunner())

    response = client.post("/api/local-video-file-picker", json={"mode": "external"})

    assert response.status_code == 200
    assert response.json() == []


def test_local_video_file_picker_reports_picker_failures(tmp_path, monkeypatch):
    def picker_failure(*, multiple: bool):
        raise FileNotFoundError("picker command missing")

    monkeypatch.setattr(app_module, "_pick_local_video_paths", picker_failure)
    client = make_client(tmp_path / "process", workspace_dir=tmp_path / "workspace", runner=FakeLocalVideoRunner())

    response = client.post("/api/local-video-file-picker", json={"mode": "external"})

    assert response.status_code == 400
    assert response.json()["detail"] == "picker command missing"


def test_pick_local_video_paths_uses_windows_file_dialog(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = "C:\\Users\\LQ\\Videos\\First Lesson.mp4\r\nD:\\Course\\Second.webm\r\n"
        stderr = ""

    def fake_run(cmd, capture_output, text, check, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    paths = app_module._pick_local_video_paths(multiple=True)

    assert paths == [Path("C:\\Users\\LQ\\Videos\\First Lesson.mp4"), Path("D:\\Course\\Second.webm")]
    assert calls[0][:4] == ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy"]
    assert "$dialog.Multiselect = $true" in calls[0][-1]
    assert "System.Windows.Forms.OpenFileDialog" in calls[0][-1]
    assert "SetProcessDpiAwarenessContext" in calls[0][-1]
    assert "$owner.TopMost = $true" in calls[0][-1]
    assert "$dialog.ShowDialog($owner)" in calls[0][-1]


def test_pick_local_video_paths_returns_empty_list_when_windows_dialog_is_cancelled(monkeypatch):
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(app_module.subprocess, "run", lambda *args, **kwargs: Result())

    assert app_module._pick_local_video_paths(multiple=False) == []


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


def test_delete_local_video_keeps_local_import_course_and_removes_video_file(tmp_path):
    workspace_dir = tmp_path / "workspace"
    client = make_client(tmp_path / "process", runner=FakeLocalVideoRunner(), workspace_dir=workspace_dir)
    client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    )

    response = client.delete("/api/items/Local-Lesson/local-video")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_url"] == "local-video://Local-Lesson"
    assert payload["local_video_path"] is None
    assert client.get("/api/items/Local-Lesson").status_code == 200
    assert not (workspace_dir / "downloads" / "Local-Lesson.mp4").exists()


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


def test_local_video_extract_job_source_first_falls_back_to_local_asr_when_online_is_disabled(tmp_path):
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
            "subtitle_source": "subtitles",
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
    assert item["transcript_source"] == "asr"
    assert item["transcript"][0]["text"] == "Local transcript"


def test_local_video_extract_job_source_first_fails_when_asr_fallback_fails(tmp_path):
    class FailingLocalAsrRunner(FakeLocalVideoRunner):
        def extract_asr_from_file(self, video_path: Path, target_dir: Path, item_id: str, language: str = "auto", progress=None):
            raise YtDlpError("local ASR engine unavailable")

    client = make_client(tmp_path, runner=FailingLocalAsrRunner())
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    ).json()

    response = client.post(
        "/api/extract-jobs",
        json={
            "url": imported["source_url"],
            "mode": "normal",
            "subtitle_source": "subtitles",
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

    assert payload["status"] == "failed"
    assert "字幕兜底失败" in payload["error"]
    item = client.get("/api/items/Local-Lesson").json()
    assert item["transcript"] == []


def test_external_video_route_serves_linked_file(tmp_path):
    source = tmp_path / "NAS Lesson.mp4"
    source.write_bytes(b"external video")
    client = make_client(tmp_path / "process", workspace_dir=tmp_path / "workspace", runner=FakeLocalVideoRunner())
    item = client.post(
        "/api/local-video-paths",
        json={"paths": [str(source)], "mode": "external"},
    ).json()[0]

    response = client.get(f"/api/items/{item['id']}/video")

    assert response.status_code == 200
    assert response.content == b"external video"


def test_external_video_route_serves_device_compatible_copy_without_mutating_source(tmp_path):
    source = tmp_path / "NAS Lesson.mp4"
    source.write_bytes(b"external video")
    workspace_dir = tmp_path / "workspace"

    class PreparingExternalRunner(FakeLocalVideoRunner):
        def prepare_ios_compatible_video_copy(self, source_path: Path, output_path: Path, progress=None):
            assert source_path == source.resolve()
            assert output_path == workspace_dir / "downloads" / "device-compatible" / "NAS-Lesson.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fixed external video")
            return output_path

    client = make_client(tmp_path / "process", workspace_dir=workspace_dir, runner=PreparingExternalRunner())
    item = client.post(
        "/api/local-video-paths",
        json={"paths": [str(source)], "mode": "external"},
    ).json()[0]

    response = client.get(f"/api/items/{item['id']}/video")

    assert response.status_code == 200
    assert response.content == b"fixed external video"
    assert source.read_bytes() == b"external video"
    assert Path(client.get(f"/api/items/{item['id']}").json()["local_video_path"]).resolve() == source.resolve()


def test_external_video_path_is_not_rewritten_to_workspace_file_with_same_name(tmp_path):
    source = tmp_path / "nas" / "Lesson.mp4"
    source.parent.mkdir()
    source.write_bytes(b"external video")
    workspace_dir = tmp_path / "workspace"
    downloads_dir = workspace_dir / "downloads"
    downloads_dir.mkdir(parents=True)
    (downloads_dir / "Lesson.mp4").write_bytes(b"workspace video")
    library = CourseLibrary(workspace_dir)
    library.save(
        CourseItem(
            id="linked-lesson",
            source_url="external-video://linked-lesson",
            title="Linked Lesson",
            created_at="2026-05-03T00:00:00Z",
            transcript=[],
            local_video_path=source,
            video_source_type="external",
        )
    )

    client = make_client(tmp_path / "process", workspace_dir=workspace_dir, runner=FakeLocalVideoRunner())
    item = client.get("/api/items/linked-lesson").json()
    video = client.get("/api/items/linked-lesson/video")

    assert Path(item["local_video_path"]).resolve() == source.resolve()
    assert video.status_code == 200
    assert video.content == b"external video"


def test_delete_external_video_course_keeps_original_file(tmp_path):
    source = tmp_path / "NAS Lesson.mp4"
    source.write_bytes(b"external video")
    client = make_client(tmp_path / "process", workspace_dir=tmp_path / "workspace", runner=FakeLocalVideoRunner())
    item = client.post(
        "/api/local-video-paths",
        json={"paths": [str(source)], "mode": "external"},
    ).json()[0]

    response = client.delete(f"/api/items/{item['id']}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert source.read_bytes() == b"external video"
    assert client.get(f"/api/items/{item['id']}").status_code == 404


def test_external_video_extract_job_runs_asr_from_linked_file(tmp_path):
    source = tmp_path / "NAS Lesson.mp4"
    source.write_bytes(b"external video")
    client = make_client(tmp_path / "process", workspace_dir=tmp_path / "workspace", runner=FakeLocalVideoRunner())
    item = client.post(
        "/api/local-video-paths",
        json={"paths": [str(source)], "mode": "external"},
    ).json()[0]

    response = client.post(
        "/api/extract-jobs",
        json={
            "url": item["source_url"],
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
    assert payload["item_id"] == item["id"]
    course = client.get(f"/api/items/{item['id']}").json()
    assert course["transcript_source"] == "asr"
    assert course["transcript"][0]["text"] == "Local transcript"


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


def test_local_video_extract_job_source_first_falls_back_to_online_asr_when_configured(tmp_path, monkeypatch):
    captured = {}

    def fake_online_asr(request, transcript_dir, item_id, yt_dlp_binary, settings, source_video_path=None, progress=None):
        captured["source_video_path"] = source_video_path
        captured["provider"] = settings.provider
        if progress:
            progress(45, "正在请求在线 ASR")
        return [TranscriptSegment(start=0, end=2, text="Online fallback transcript")]

    monkeypatch.setattr(app_module, "extract_online_asr_transcript", fake_online_asr)
    client = make_client(
        tmp_path,
        runner=FakeLocalVideoRunner(),
        settings=Settings(
            data_dir=tmp_path,
            online_asr=OnlineAsrSettings(
                provider="xai",
                xai={"api_key": "xai-test"},
            ),
        ),
    )
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    ).json()

    response = client.post(
        "/api/extract-jobs",
        json={
            "url": imported["source_url"],
            "mode": "normal",
            "subtitle_source": "subtitles",
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
    assert item["transcript"][0]["text"] == "Online fallback transcript"
    assert captured["source_video_path"].name == "Local-Lesson.mp4"
    assert captured["provider"] == "xai"


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


def test_playback_source_resolves_missing_remote_stream_url(tmp_path):
    runner = CountingMetadataRunner()
    workspace = tmp_path / "workspace"
    client = make_client(tmp_path, runner=runner, workspace_dir=workspace)
    library = CourseLibrary(workspace)
    library.save(
        CourseItem(
            id="remote-lesson",
            source_url="https://www.youtube.com/watch?v=remote",
            title="Remote Lesson",
            created_at="2026-06-07T00:00:00+00:00",
            duration=None,
            metadata=VideoMetadata(
                id="remote",
                title="Remote Lesson",
                webpage_url="https://www.youtube.com/watch?v=remote",
                extractor="youtube",
                stream_url=None,
                hls_manifest_url=None,
            ),
        )
    )

    response = client.post("/api/items/remote-lesson/playback-source")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["stream_url"] == "https://cdn.example.com/sample.m3u8"
    assert payload["duration"] == 42
    assert runner.fetch_count == 1
    persisted = client.get("/api/items/remote-lesson").json()
    assert persisted["metadata"]["stream_url"] == "https://cdn.example.com/sample.m3u8"


def test_playback_source_refreshes_expired_remote_stream_url(tmp_path):
    runner = CountingMetadataRunner()
    workspace = tmp_path / "workspace"
    client = make_client(tmp_path, runner=runner, workspace_dir=workspace)
    library = CourseLibrary(workspace)
    library.save(
        CourseItem(
            id="expired-remote-lesson",
            source_url="https://www.youtube.com/watch?v=expired",
            title="Expired Remote Lesson",
            created_at="2026-06-07T00:00:00+00:00",
            duration=10,
            metadata=VideoMetadata(
                id="expired",
                title="Expired Remote Lesson",
                webpage_url="https://www.youtube.com/watch?v=expired",
                extractor="youtube",
                stream_url="https://rr.example.googlevideo.com/videoplayback?expire=1&sig=old",
                hls_manifest_url=None,
            ),
        )
    )

    response = client.post("/api/items/expired-remote-lesson/playback-source")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["stream_url"] == "https://cdn.example.com/sample.m3u8"
    assert payload["duration"] == 10
    assert runner.fetch_count == 1


def test_playback_source_refreshes_expired_hls_manifest_url(tmp_path):
    runner = CountingMetadataRunner()
    workspace = tmp_path / "workspace"
    client = make_client(tmp_path, runner=runner, workspace_dir=workspace)
    library = CourseLibrary(workspace)
    library.save(
        CourseItem(
            id="expired-hls-lesson",
            source_url="https://www.youtube.com/watch?v=expired-hls",
            title="Expired HLS Lesson",
            created_at="2026-06-07T00:00:00+00:00",
            duration=10,
            metadata=VideoMetadata(
                id="expired-hls",
                title="Expired HLS Lesson",
                webpage_url="https://www.youtube.com/watch?v=expired-hls",
                extractor="youtube",
                stream_url=None,
                hls_manifest_url="https://manifest.googlevideo.com/api/manifest/hls_variant/expire/1/id/expired-hls",
            ),
        )
    )

    response = client.post("/api/items/expired-hls-lesson/playback-source")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["stream_url"] == "https://cdn.example.com/sample.m3u8"
    assert runner.fetch_count == 1


def test_playback_source_keeps_fresh_remote_stream_url(tmp_path):
    runner = CountingMetadataRunner()
    workspace = tmp_path / "workspace"
    client = make_client(tmp_path, runner=runner, workspace_dir=workspace)
    library = CourseLibrary(workspace)
    expires_at = int(datetime.now(timezone.utc).timestamp()) + 3600
    stream_url = f"https://rr.example.googlevideo.com/videoplayback?expire={expires_at}&sig=fresh"
    library.save(
        CourseItem(
            id="fresh-remote-lesson",
            source_url="https://www.youtube.com/watch?v=fresh",
            title="Fresh Remote Lesson",
            created_at="2026-06-07T00:00:00+00:00",
            duration=10,
            metadata=VideoMetadata(
                id="fresh",
                title="Fresh Remote Lesson",
                webpage_url="https://www.youtube.com/watch?v=fresh",
                extractor="youtube",
                stream_url=stream_url,
                hls_manifest_url=None,
            ),
        )
    )

    response = client.post("/api/items/fresh-remote-lesson/playback-source")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["stream_url"] == stream_url
    assert payload["duration"] == 10
    assert runner.fetch_count == 0


def test_playback_source_does_not_refresh_local_workspace_video(tmp_path):
    runner = CountingMetadataRunner()
    client = make_client(tmp_path, runner=runner)
    imported = client.post(
        "/api/local-videos",
        files={"file": ("Local Lesson.mp4", b"local video", "video/mp4")},
    ).json()

    response = client.post(f"/api/items/{imported['id']}/playback-source")

    assert response.status_code == 200
    assert response.json()["local_video_path"]
    assert runner.fetch_count == 0


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


def test_video_route_prepares_downloaded_workspace_file_before_serving(tmp_path):
    process_dir = tmp_path / "process"
    workspace_dir = tmp_path / "workspace"
    downloads_dir = workspace_dir / "downloads"
    downloads_dir.mkdir(parents=True)
    source = downloads_dir / "bad-cache.mp4"
    source.write_bytes(b"mpegts")
    library = CourseLibrary(workspace_dir)
    library.save(CourseItem(
        id="course",
        title="Course",
        source_url="https://example.com/course",
        created_at="2026-01-01T00:00:00+00:00",
        local_video_path=Path("downloads/bad-cache.mp4"),
        video_source_type="workspace",
    ))

    class PreparingRunner(FakeRunner):
        def prepare_ios_compatible_video(self, path: Path, progress=None):
            assert path == source
            prepared = downloads_dir / "course.mp4"
            prepared.write_bytes(b"fixed video")
            source.unlink()
            return prepared

    client = make_client(process_dir, workspace_dir=workspace_dir, runner=PreparingRunner())

    response = client.get("/api/items/course/video")

    assert response.status_code == 200
    assert response.content == b"fixed video"
    assert client.get("/api/items/course").json()["local_video_path"] == "downloads/course.mp4"


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
