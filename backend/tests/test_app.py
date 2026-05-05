from pathlib import Path
from time import sleep

from fastapi.testclient import TestClient

from course_navigator.app import create_app
from course_navigator.config import Settings
from course_navigator.models import TranscriptSegment, VideoMetadata
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


def test_translation_job_writes_translated_transcript(tmp_path, monkeypatch):
    def fake_translate(**kwargs):
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
) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path,
            runner=runner or FakeRunner(),
            settings=settings or Settings(data_dir=tmp_path),
            env_path=env_path,
        )
    )
