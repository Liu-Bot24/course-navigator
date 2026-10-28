"""Subtitle language and source provenance across edits, uploads and extraction."""

from pathlib import Path
from threading import Event

from course_navigator.models import TranscriptSegment
from test_app import FakeLocalVideoRunner, FakeRunner, make_client
from test_data_integrity import URL, terminal


def test_manual_subtitle_replacement_does_not_inherit_video_language(tmp_path):
    class EnglishVideo(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.language = "en"
            return metadata

    client = make_client(tmp_path, runner=EnglishVideo())
    item = client.post("/api/extract", json={"url": URL}).json()
    # A replacement file of unknown language is sent with an explicit null.
    assert client.put(f"/api/items/{item['id']}/transcript", json={"language": None, "transcript": [
        {"start": 0, "end": 5, "text": "这是用户重新导入的中文字幕，翻译成英语需要模型。"}
    ]}).status_code == 200
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "en"}).json()
    # No provider is configured. Copying Chinese as an English translation must
    # not be reported as success based on the video's old English language tag.
    assert terminal(client, job["job_id"])["status"] == "failed"


def test_subtitle_edit_keeps_known_track_language(tmp_path):
    client = make_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    path = f"/api/items/{item['id']}/transcript"
    assert client.put(path, json={"language": "zh-CN", "transcript": [
        {"start": 0, "end": 4, "text": "今天我们学习梯度下将。"}]}).json()["transcript_language"] == "zh-CN"
    # Editing or accepting an ASR suggestion sends only the corrected text.
    edited = client.put(path, json={"transcript": [{"start": 0, "end": 4, "text": "今天我们学习梯度下降。"}]})
    assert edited.status_code == 200
    assert edited.json()["transcript_language"] == "zh-CN"
    # Same-language output still needs no model after the edit.
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "zh-CN"}).json()
    assert terminal(client, job["job_id"])["status"] == "succeeded"
    # An explicit null still marks a replacement track as unknown.
    cleared = client.put(path, json={"language": None, "transcript": [{"start": 0, "end": 4, "text": "Replaced."}]})
    assert cleared.json()["transcript_language"] is None


def test_rebinding_external_video_invalidates_running_asr_input(tmp_path):
    started, release = Event(), Event()
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    first.write_bytes(b"first video")
    second.write_bytes(b"second video")

    class BlockingLocalRunner(FakeLocalVideoRunner):
        def extract_asr_from_file(self, video_path, target_dir, item_id, language="auto", progress=None):
            assert Path(video_path).resolve() == first.resolve()
            started.set()
            assert release.wait(3)
            return [TranscriptSegment(start=0, end=2, text="Transcript from the old video")]

    client = make_client(tmp_path / "data", runner=BlockingLocalRunner())
    item = client.post("/api/local-video-paths", json={"paths": [str(first)], "mode": "external"}).json()[0]
    job = client.post("/api/extract-jobs", json={"url": item["source_url"], "subtitle_source": "asr"}).json()
    try:
        assert started.wait(2)
        bound = client.post(f"/api/items/{item['id']}/video-source", json={
            "source_type": "external", "path": str(second)})
        assert bound.status_code == 200
    finally:
        release.set()
    assert terminal(client, job["job_id"])["status"] == "failed"
    current = client.get(f"/api/items/{item['id']}").json()
    assert Path(current["local_video_path"]).resolve() == second.resolve()
    assert current["transcript"] == []


def test_selected_subtitle_track_language_takes_precedence_over_video_language(tmp_path):
    class ChineseTrack(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.language = "en"
            metadata.subtitles = ["zh-CN"]
            return metadata

        def extract_subtitles(self, *args, **kwargs):
            return [TranscriptSegment(start=0, end=3, text="这是所选中文字幕。")]

    client = make_client(tmp_path, runner=ChineseTrack())
    item = client.post("/api/extract", json={"url": URL}).json()
    assert item["transcript_language"] == "zh-CN"
    matching = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "zh-CN"}).json()
    assert terminal(client, matching["job_id"])["status"] == "succeeded"
    differing = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "en"}).json()
    assert terminal(client, differing["job_id"])["status"] == "failed"


def test_explicit_language_on_manual_subtitles_allows_same_language_reuse(tmp_path):
    client = make_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    client.put(f"/api/items/{item['id']}/transcript", json={"language": "en", "transcript": [
        {"start": 0, "end": 3, "text": "User confirmed this is English."}
    ]})
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "en"}).json()
    assert terminal(client, job["job_id"])["status"] == "succeeded"


def test_missing_extractor_identity_falls_back_to_url(tmp_path):
    class UnknownIdentity(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.id = "unknown"
            metadata.extractor = "unknown"
            return metadata

    client = make_client(tmp_path, runner=UnknownIdentity())
    first = client.post("/api/preview", json={"url": "https://example.com/first"}).json()
    second = client.post("/api/preview", json={"url": "https://example.com/second"}).json()
    assert first["id"] != second["id"]
    assert len(client.get("/api/items").json()) == 2
