"""Source binding, local video ownership, ASR queue and translation regressions."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event, Lock
from urllib.parse import parse_qs, urlparse

import pytest
import httpx

import course_navigator.app as app_module
from course_navigator.config import Settings
from course_navigator.library import CourseLibrary
from test_app import FakeRunner, make_client
from test_data_integrity import URL, terminal


@pytest.mark.parametrize("operation", ["preview", "extract"])
def test_bound_remote_source_can_be_resolved_again(tmp_path, operation):
    class SourceIds(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.id = parse_qs(urlparse(request.url).query)["v"][0]
            return metadata

    client = make_client(tmp_path, runner=SourceIds())
    item = client.post("/api/preview", json={"url": URL}).json()
    new_url = "https://www.youtube.com/watch?v=new-video"
    assert client.post(f"/api/items/{item['id']}/video-source", json={"source_type": "remote", "url": new_url}).status_code == 200
    response = client.post(f"/api/{operation}", json={"url": new_url})
    assert response.status_code == 200
    assert response.json()["id"] == item["id"]
    assert response.json()["metadata"]["id"] == "new-video"


def test_remote_to_workspace_binding_does_not_steal_the_old_remote_source(tmp_path, monkeypatch):
    video = tmp_path / "chosen.mp4"
    video.write_bytes(b"new local source")
    client = make_client(tmp_path)
    remote = client.post("/api/preview", json={"url": URL}).json()
    monkeypatch.setattr(app_module, "_pick_local_video_paths", lambda **_: [video])
    bound = client.post(f"/api/items/{remote['id']}/workspace-video-picker")
    assert bound.status_code == 200
    new_remote = client.post("/api/preview", json={"url": URL})
    assert new_remote.status_code == 200
    assert new_remote.json()["id"] != remote["id"]
    assert new_remote.json()["source_url"] == URL
    assert client.get(f"/api/items/{remote['id']}/video").content == b"new local source"


@pytest.mark.parametrize("extractor", ["generic", "fixture-platform"])
def test_distinct_ports_have_distinct_source_identities(tmp_path, extractor):
    class SameId(FakeRunner):
        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            metadata.extractor = extractor
            return metadata

    client = make_client(tmp_path, runner=SameId())
    first = client.post("/api/preview", json={"url": "http://media.example:8001/course/1"}).json()
    second = client.post("/api/preview", json={"url": "http://media.example:8002/course/1"}).json()
    assert first["id"] != second["id"]
    assert second["source_url"] == "http://media.example:8002/course/1"


def test_youtube_aliases_and_explicit_default_port_still_match(tmp_path):
    client = make_client(tmp_path)
    first = client.post("/api/preview", json={"url": URL}).json()
    alias = client.post("/api/preview", json={"url": "https://youtu.be:443/abc123"}).json()
    assert first["id"] == alias["id"]


def test_stale_workspace_picker_cannot_overwrite_reimported_video(tmp_path, monkeypatch):
    selected = tmp_path / "selected.mp4"
    selected.write_bytes(b"old operation selected bytes")
    client = make_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    picker_started, release = Event(), Event()

    def picker(**_):
        picker_started.set()
        assert release.wait(4)
        return [selected]

    monkeypatch.setattr(app_module, "_pick_local_video_paths", picker)
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale = pool.submit(client.post, f"/api/items/{item['id']}/workspace-video-picker")
        try:
            assert picker_started.wait(2)
            assert client.delete(f"/api/items/{item['id']}").status_code == 200
            new = client.post("/api/local-videos", files={"file": (f"{item['id']}.mp4", b"new instance bytes", "video/mp4")}).json()
            assert new["id"] == item["id"]
        finally:
            release.set()
        assert stale.result(timeout=3).status_code == 409
    assert client.get(f"/api/items/{new['id']}/video").content == b"new instance bytes"
    assert [path.read_bytes() for path in (tmp_path / "downloads").rglob("*.mp4")] == [b"new instance bytes"]


def test_stale_local_video_delete_cannot_remove_reimported_file(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    item = client.post("/api/local-videos", files={"file": ("lesson.mp4", b"old", "video/mp4")}).json()
    read_done, release, once = Event(), Event(), Lock()
    original_get = CourseLibrary.get
    captured = False

    def paused_get(self, item_id):
        nonlocal captured
        result = original_get(self, item_id)
        with once:
            pause = item_id == item["id"] and not captured
            if pause:
                captured = True
        if pause:
            read_done.set()
            assert release.wait(4)
        return result

    monkeypatch.setattr(CourseLibrary, "get", paused_get)
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale = pool.submit(client.delete, f"/api/items/{item['id']}/local-video")
        try:
            assert read_done.wait(2)
            assert client.delete(f"/api/items/{item['id']}").status_code == 200
            new = client.post("/api/local-videos", files={"file": ("lesson.mp4", b"new instance", "video/mp4")}).json()
        finally:
            release.set()
        assert stale.result(timeout=3).status_code == 409
    response = client.get(f"/api/items/{new['id']}/video")
    assert response.status_code == 200
    assert response.content == b"new instance"


def asr_client(tmp_path):
    return make_client(tmp_path, settings=Settings(data_dir=tmp_path, llm_base_url="https://fixture.test/v1",
                                                  llm_model="test", llm_api_key="test-only"))


@pytest.mark.parametrize("segments", [[{"start": 2, "end": 1, "text": "Invalid interval"}],
                                       [{"start": 0, "end": 1, "text": "   "}]])
def test_invalid_asr_does_not_consume_queue_capacity(tmp_path, monkeypatch, segments):
    monkeypatch.setattr(app_module, "MAX_ACTIVE_JOBS", 2)
    monkeypatch.setattr(app_module, "suggest_asr_corrections", lambda **_: [])
    client = asr_client(tmp_path)
    item = client.post("/api/extract", json={"url": URL}).json()
    for _ in range(4):
        response = client.post(f"/api/items/{item['id']}/asr-correction-jobs", json={"transcript": segments})
        assert response.status_code == 400
    valid = client.post(f"/api/items/{item['id']}/asr-correction-jobs", json={})
    assert valid.status_code == 200
    assert terminal(client, valid.json()["job_id"])["status"] == "succeeded"


def test_asr_cancel_before_final_publication_prevents_result(tmp_path, monkeypatch):
    finalizing, release = Event(), Event()
    original = app_module._coerce_asr_suggestions

    def pause(suggestions, transcript):
        finalizing.set()
        assert release.wait(4)
        return original(suggestions, transcript)

    monkeypatch.setattr(app_module, "suggest_asr_corrections", lambda **_: [])
    monkeypatch.setattr(app_module, "_coerce_asr_suggestions", pause)
    client = asr_client(tmp_path)
    item = client.post("/api/extract", json={"url": URL}).json()
    job = client.post(f"/api/items/{item['id']}/asr-correction-jobs", json={}).json()
    try:
        assert finalizing.wait(2)
        assert client.post(f"/api/jobs/{job['job_id']}/cancel").json()["status"] == "cancelling"
    finally:
        release.set()
    assert terminal(client, job["job_id"])["status"] == "cancelled"
    assert client.get(f"/api/asr-correction-jobs/{job['job_id']}/result").status_code == 404


@pytest.mark.parametrize("kind", ["extract", "download"])
def test_cancelled_tail_work_stays_within_physical_queue_limit(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(app_module, "MAX_ACTIVE_JOBS", 8)
    pools = []
    original_pool = app_module.ThreadPoolExecutor

    class RecordingPool(original_pool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.submissions = []
            pools.append(self)

        def submit(self, *args, **kwargs):
            future = super().submit(*args, **kwargs)
            self.submissions.append(future)
            return future

    monkeypatch.setattr(app_module, "ThreadPoolExecutor", RecordingPool)
    started, release = Event(), Event()

    class Blocking(FakeRunner):
        def extract_subtitles(self, *args, **kwargs):
            started.set()
            assert release.wait(6)
            return super().extract_subtitles(*args, **kwargs)

        def download_video(self, *args, **kwargs):
            started.set()
            assert release.wait(6)
            return super().download_video(*args, **kwargs)

    client = make_client(tmp_path, runner=Blocking())
    item = client.post("/api/preview", json={"url": URL}).json()
    route = "/api/extract-jobs" if kind == "extract" else f"/api/items/{item['id']}/download-jobs"
    head = client.post(route, json={"url": URL}).json()
    accepted = [head["job_id"]]
    try:
        assert started.wait(2)
        for _ in range(24):
            response = client.post(route, json={"url": URL})
            if response.status_code == 429:
                continue
            assert response.status_code == 200
            job_id = response.json()["job_id"]
            accepted.append(job_id)
            assert client.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"
        pool = pools[1 if kind == "extract" else 0]
        assert len(accepted) <= 8
        assert len(pool.submissions) <= 8
        assert pool._work_queue.qsize() <= 7
    finally:
        release.set()
    assert terminal(client, head["job_id"])["status"] == "succeeded"
    for job_id in accepted[1:]:
        assert terminal(client, job_id)["status"] == "cancelled"


@pytest.mark.parametrize("language,text", [("en", "This complete sentence is already written in English."),
                                           ("zh-CN", "这是一句已经使用中文表达的完整课程字幕，不需要改变意思。")])
def test_unknown_language_model_confirmed_echo_is_kept_by_api(tmp_path, monkeypatch, language, text):
    calls = []
    original_post = httpx.AsyncClient.post

    async def post(self, url, **kwargs):
        if not str(url).startswith("https://fixture.test/"):
            return await original_post(self, url, **kwargs)
        system = kwargs["json"]["messages"][0]["content"]
        calls.append(system)
        if "already_target_language" in system:
            payload = {"already_target_language": [True]}
        elif "translated_transcript" in system:
            payload = {"translated_transcript": [{"start": 0, "end": 4, "text": text}]}
        elif "translated_title" in system:
            payload = {"translated_title": "Lesson"}
        else:
            payload = {"summary": "A course subtitle."}
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    client = asr_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    client.put(f"/api/items/{item['id']}/transcript", json={"transcript": [{"start": 0, "end": 4, "text": text}]})
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": language}).json()
    assert terminal(client, job["job_id"])["status"] == "succeeded"
    returned = client.get(f"/api/items/{item['id']}").json()["study"]["translated_transcript"]
    assert returned == [{"start": 0, "end": 4, "text": text}]
    assert any("translated_transcript" in prompt for prompt in calls)
    assert any("already_target_language" in prompt for prompt in calls)


def test_known_matching_source_is_not_hidden_from_api(tmp_path):
    client = make_client(tmp_path)
    item = client.post("/api/extract", json={"url": URL}).json()
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "en"}).json()
    assert terminal(client, job["job_id"])["status"] == "succeeded"
    assert client.get(f"/api/items/{item['id']}").json()["study"]["translated_transcript"] == item["transcript"]


@pytest.mark.parametrize("failure", ["missing", "http_failure", "unconfirmed_echo"])
def test_failed_translation_cannot_be_filled_with_source_as_success(tmp_path, monkeypatch, failure):
    text = "Esta frase completa está escrita en español y necesita una traducción al inglés."
    original_post = httpx.AsyncClient.post

    async def post(self, url, **kwargs):
        if not str(url).startswith("https://fixture.test/"):
            return await original_post(self, url, **kwargs)
        system = kwargs["json"]["messages"][0]["content"]
        if "already_target_language" in system:
            payload = {"already_target_language": [False]}
        elif "translated_transcript" in system:
            if failure == "http_failure":
                return httpx.Response(503, headers={"retry-after": "0"}, request=httpx.Request("POST", url))
            payload = {"translated_transcript": [] if failure == "missing" else [{"start": 0, "end": 4, "text": text}]}
        elif "translated_title" in system:
            payload = {"translated_title": "Lesson"}
        else:
            payload = {"summary": "A course subtitle."}
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    client = asr_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    client.put(f"/api/items/{item['id']}/transcript", json={"transcript": [{"start": 0, "end": 4, "text": text}]})
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "en"}).json()
    assert terminal(client, job["job_id"])["status"] == "failed"
    assert client.get(f"/api/items/{item['id']}").json()["study"] is None


def test_delete_during_workspace_copy_only_cleans_old_owned_files(tmp_path, monkeypatch):
    from course_navigator import media_storage

    chosen = tmp_path / "chosen.mp4"
    chosen.write_bytes(b"old picker selection")
    client = make_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    monkeypatch.setattr(app_module, "_pick_local_video_paths", lambda **_: [chosen])
    copied, release = Event(), Event()
    original_copy = media_storage.shutil.copy2

    def pause_after_copy(source, destination, *args, **kwargs):
        result = original_copy(source, destination, *args, **kwargs)
        if item["instance_id"] in Path(destination).parts:
            copied.set()
            assert release.wait(4)
        return result

    monkeypatch.setattr(media_storage.shutil, "copy2", pause_after_copy)
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale = pool.submit(client.post, f"/api/items/{item['id']}/workspace-video-picker")
        try:
            assert copied.wait(2)
            assert client.delete(f"/api/items/{item['id']}").status_code == 200
            new = client.post("/api/local-videos", files={"file": (f"{item['id']}.mp4", b"replacement bytes", "video/mp4")}).json()
        finally:
            release.set()
        assert stale.result(timeout=3).status_code == 409
    assert client.get(f"/api/items/{new['id']}/video").content == b"replacement bytes"
    assert [path.read_bytes() for path in (tmp_path / "downloads").rglob("*.mp4")] == [b"replacement bytes"]


def test_failed_detach_record_write_restores_video_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    original = make_client(tmp_path)
    client = TestClient(original.app, raise_server_exceptions=False, base_url="http://127.0.0.1")
    item = client.post("/api/local-videos", files={"file": ("lesson.mp4", b"recoverable video", "video/mp4")}).json()
    original_write = CourseLibrary._write

    def fail_detach(self, course):
        if course.id == item["id"] and course.local_video_path is None:
            raise OSError("Simulated record write failure")
        return original_write(self, course)

    monkeypatch.setattr(CourseLibrary, "_write", fail_detach)
    assert client.delete(f"/api/items/{item['id']}/local-video").status_code == 500
    assert client.get(f"/api/items/{item['id']}/video").content == b"recoverable video"
    assert not list((tmp_path / "downloads" / ".retired").rglob("*.mp4"))
