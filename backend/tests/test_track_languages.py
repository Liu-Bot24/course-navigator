"""API behaviour for the actual language of subtitle tracks."""
import json

import httpx
import pytest

from course_navigator.models import TranscriptSegment
from test_app import FakeRunner, make_client
from test_data_integrity import URL, terminal
from test_source_and_queue_regressions import asr_client


@pytest.mark.parametrize("track,target,text", [
    ("ai-zh", "zh-CN", "这是一句完整的中文字幕。"),
    ("ai-en", "en", "This subtitle is already English."),
    ("ai-ja", "ja", "これは日本語の字幕です。"),
])
def test_platform_ai_track_language_survives_extraction(tmp_path, track, target, text):
    class TrackRunner(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.extractor = "bilibili"
            metadata.subtitles = [track]
            return metadata

        def extract_subtitles(self, request, target_dir, metadata=None):
            return [TranscriptSegment(start=0, end=4, text=text)]

    client = make_client(tmp_path, runner=TrackRunner())
    item = client.post("/api/extract", json={"url": "https://www.bilibili.com/video/BVfixture"}).json()
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": target}).json()
    assert terminal(client, job["job_id"])["status"] == "succeeded"
    assert client.get(f"/api/items/{item['id']}").json()["study"]["translated_transcript"] == item["transcript"]


@pytest.mark.parametrize("source,target,confirmed", [
    ("你好", "en", False), ("Hola.", "en", False), ("学习", "ja", False),
    ("Hello.", "en", True), ("こんにちは", "ja", True), ("OpenAI", "ja", True),
    ("API", "zh-CN", True), ("42", "en", False),
])
@pytest.mark.parametrize("source_language", [None, "es"])
def test_echo_completion_respects_language_evidence(tmp_path, monkeypatch, source, target, confirmed, source_language):
    async def post(self, url, **kwargs):
        system = kwargs["json"]["messages"][0]["content"]
        if "already_target_language" in system:
            payload = {"already_target_language": [confirmed]}
        elif "translated_transcript" in system:
            payload = {"translated_transcript": [{"start": 0, "end": 4, "text": source}]}
        elif "translated_title" in system:
            payload = {"translated_title": "Lesson"}
        else:
            payload = {"summary": "A subtitle."}
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    client = asr_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    client.put(f"/api/items/{item['id']}/transcript", json={
        "transcript": [{"start": 0, "end": 4, "text": source}], "language": source_language})
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": target}).json()
    succeeds = confirmed or source == "42"
    assert terminal(client, job["job_id"])["status"] == ("succeeded" if succeeds else "failed")
    study = client.get(f"/api/items/{item['id']}").json()["study"]
    if succeeds:
        assert study["translated_transcript"][0]["text"] == source
    else:
        assert study is None


@pytest.mark.parametrize("source", ["42", "1 + 2 = 3", "…"])
def test_numeric_and_symbol_echoes_need_no_language_guess(source):
    from course_navigator import ai
    segment = TranscriptSegment(start=0, end=1, text=source)
    assert not ai._needs_translation_repair(segment, segment, "ja")


@pytest.mark.parametrize("target,succeeds", [("zh-CN", True), ("ja", False)])
def test_previously_saved_ai_track_language_is_compatible(tmp_path, target, succeeds):
    client = make_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    client.put(f"/api/items/{item['id']}/transcript", json={
        "transcript": [{"start": 0, "end": 4, "text": "这是一句中文课程字幕。"}], "language": "ai-zh"})
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": target}).json()
    assert terminal(client, job["job_id"])["status"] == ("succeeded" if succeeds else "failed")
