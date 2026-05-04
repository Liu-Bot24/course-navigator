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


def test_model_settings_can_be_read_and_updated(tmp_path):
    env_path = tmp_path / ".env"
    client = make_client(
        tmp_path,
        env_path=env_path,
        settings=Settings(
            data_dir=tmp_path,
            llm_base_url="https://api.siliconflow.cn/v1",
            llm_model="deepseek-ai/DeepSeek-V3.2",
            llm_api_key="sk-test-secret-value",
        ),
    )

    initial = client.get("/api/settings/model")

    assert initial.status_code == 200
    assert initial.json()["profiles"][0]["name"] == "DeepSeek V3.2"
    assert initial.json()["translation_model_id"] == "default"

    updated = client.put(
        "/api/settings/model",
        json={
            "profiles": [
                {
                    "id": "fast",
                    "name": "Hunyuan Fast",
                    "provider_type": "openai",
                    "base_url": "https://api.example.com/v1",
                    "model": "hunyuan-lite",
                    "context_window": 64000,
                    "max_tokens": 4096,
                    "api_key": "sk-fast-secret",
                },
                {
                    "id": "long",
                    "name": "Mimo Long",
                    "provider_type": "anthropic",
                    "base_url": "https://api.example.com/v1",
                    "model": "mimo-v2.5-pro",
                    "context_window": 1000000,
                    "max_tokens": 32000,
                    "api_key": "sk-long-secret",
                },
            ],
            "translation_model_id": "fast",
            "learning_model_id": "long",
            "global_model_id": "long",
            "study_detail_level": "detailed",
            "task_parameters": {
                "semantic_segmentation": {"temperature": 0.24, "max_tokens": 9000},
                "high_fidelity": {"temperature": 0.42, "max_tokens": 16000},
            },
        },
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["translation_model_id"] == "fast"
    assert payload["learning_model_id"] == "long"
    assert payload["global_model_id"] == "long"
    assert payload["study_detail_level"] == "detailed"
    assert payload["task_parameters"]["semantic_segmentation"] == {"temperature": 0.24, "max_tokens": 9000}
    assert payload["task_parameters"]["high_fidelity"] == {"temperature": 0.42, "max_tokens": 16000}
    assert payload["profiles"][1]["provider_type"] == "anthropic"
    assert payload["profiles"][1]["context_window"] == 1000000
    assert payload["profiles"][1]["max_tokens"] == 32000
    assert payload["profiles"][0]["api_key_preview"] != "sk-fast-secret"
    assert "api_key" not in payload["profiles"][0]
    written = env_path.read_text(encoding="utf-8")
    assert "COURSE_NAVIGATOR_MODEL_PROFILES" in written
    assert "COURSE_NAVIGATOR_TRANSLATION_MODEL_ID" in written
    assert "COURSE_NAVIGATOR_STUDY_DETAIL_LEVEL" in written
    assert "COURSE_NAVIGATOR_TASK_PARAMETERS" in written


def test_model_list_endpoint_uses_saved_profile_key(tmp_path, monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "deepseek-ai/DeepSeek-V3.2"}, {"id": "Qwen/Qwen3"}]}

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
                    "name": "DeepSeek",
                    "base_url": "https://api.example.com/v1/chat/completions",
                    "model": "deepseek-ai/DeepSeek-V3.2",
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
    assert response.json()["models"] == ["deepseek-ai/DeepSeek-V3.2", "Qwen/Qwen3"]
    assert captured["url"] == "https://api.example.com/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer sk-saved"


def test_model_list_endpoint_adds_v1_for_minimax_anthropic_base(tmp_path, monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "MiniMax-M2.7"}]}

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
            "base_url": "https://api.minimaxi.com/anthropic",
            "api_key": "sk-request",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == ["MiniMax-M2.7"]
    assert captured["url"] == "https://api.minimaxi.com/anthropic/v1/models"
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
