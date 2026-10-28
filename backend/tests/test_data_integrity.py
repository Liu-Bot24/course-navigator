"""Data-integrity scenarios: concurrent edits, deletion, caching and job limits."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest

import course_navigator.app as app_module
import course_navigator.ai as ai
from course_navigator.ai import translate_transcript_material
from course_navigator.models import StudyMaterial, TranscriptSegment
from test_app import FakeRunner, make_client


URL = "https://www.youtube.com/watch?v=abc123"


def material():
    return StudyMaterial(one_line="Generated", time_map=[], outline=[],
                         detailed_notes="Notes", high_fidelity_text="Text")


def terminal(client, job_id):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        sleep(0.01)
    pytest.fail(f"Job did not finish: {job}")


@pytest.mark.parametrize("edit", ["title", "transcript"])
def test_study_does_not_overwrite_edits_made_while_model_runs(tmp_path, monkeypatch, edit):
    started, release = Event(), Event()

    def generate(**kwargs):
        started.set()
        assert release.wait(5)
        return material()

    monkeypatch.setattr(app_module, "generate_study_material", generate)
    client = make_client(tmp_path)
    item = client.post("/api/extract", json={"url": URL}).json()
    job = client.post(f"/api/items/{item['id']}/study-jobs").json()
    try:
        assert started.wait(3)
        if edit == "title":
            result = client.patch(f"/api/items/{item['id']}", json={"title": "My new title"})
        else:
            result = client.put(f"/api/items/{item['id']}/transcript", json={
                "transcript": [{"start": 0, "end": 3, "text": "Corrected source"}]})
        assert result.status_code == 200
    finally:
        release.set()
    terminal(client, job["job_id"])
    current = client.get(f"/api/items/{item['id']}").json()
    if edit == "title":
        assert current["title"] == "My new title"
    else:
        assert current["transcript"][0]["text"] == "Corrected source"
        assert current["study"] is None


@pytest.mark.parametrize("reimport", [False, True])
def test_deleted_course_is_not_restored_by_old_extraction(tmp_path, reimport):
    started, release = Event(), Event()

    class BlockingRunner(FakeRunner):
        def extract_subtitles(self, *args, **kwargs):
            started.set()
            assert release.wait(5)
            return super().extract_subtitles(*args, **kwargs)

    client = make_client(tmp_path, runner=BlockingRunner())
    item = client.post("/api/preview", json={"url": URL}).json()
    job = client.post("/api/extract-jobs", json={"url": URL}).json()
    try:
        assert started.wait(3)
        assert client.delete(f"/api/items/{item['id']}").status_code == 200
        if reimport:
            replacement = client.post("/api/preview", json={"url": URL}).json()
    finally:
        release.set()
    terminal(client, job["job_id"])
    items = client.get("/api/items").json()
    if reimport:
        assert len(items) == 1
        assert items[0]["transcript"] == replacement["transcript"] == []
    else:
        assert items == []


def test_same_platform_id_on_different_origins_does_not_mix_courses(tmp_path):
    client = make_client(tmp_path)
    first = client.post("/api/extract", json={"url": URL}).json()
    second = client.post("/api/preview", json={"url": "https://other.example/abc123"}).json()
    assert first["id"] != second["id"]
    assert second["transcript"] == []
    assert len(client.get("/api/items").json()) == 2
    again = client.post("/api/preview", json={"url": "https://other.example/abc123"}).json()
    assert again["id"] == second["id"]


def test_workspace_migration_does_not_restore_deleted_data(tmp_path):
    legacy, workspace = tmp_path / "legacy", tmp_path / "workspace"
    source = legacy / "items"
    source.mkdir(parents=True)
    (source / "lesson.json").write_text("{}")
    app_module._prepare_workspace(workspace, legacy)
    (workspace / "items" / "lesson.json").unlink()
    app_module._prepare_workspace(workspace, legacy)
    assert not (workspace / "items" / "lesson.json").exists()


@pytest.mark.parametrize("text, target", [
    ("今天我们学习课程中的重要知识并理解每一个具体的概念和方法", "ja"),
    ("Este es un curso sobre los principios de la ciencia y las maneras de entender el mundo que nos rodea todos los dias", "en"),
])
def test_script_alone_does_not_prove_target_language(text, target):
    with pytest.raises(ValueError, match="未配置可用的翻译模型"):
        translate_transcript_material("Lesson", [TranscriptSegment(start=0, end=3, text=text)],
                                      provider=None, output_language=target)


def test_preview_keeps_collection_group(tmp_path):
    client = make_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    assert client.patch(f"/api/items/{item['id']}", json={"collection_group_title": "My group"}).status_code == 200
    refreshed = client.post("/api/preview", json={"url": URL}).json()
    assert refreshed["collection_group_title"] == "My group"


def test_binding_new_remote_source_invalidates_old_playback_metadata(tmp_path):
    client = make_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    result = client.post(f"/api/items/{item['id']}/video-source", json={
        "source_type": "remote", "url": "https://other.example/new"})
    assert result.status_code == 200
    updated = result.json()
    assert updated["metadata"] is None or not updated["metadata"].get("stream_url")
    assert updated["title"] == item["title"]


def test_cancellation_interrupts_a_real_waiting_http_request():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    received, release, cancel = Event(), Event(), Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.set()
            release.wait(5)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"{}"}}]}')
            except OSError:
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ai.translate_transcript_material,
                                 "Lesson", [TranscriptSegment(start=0, end=2, text="A long source sentence.")],
                                 ai.LlmProvider(base_url=f"http://127.0.0.1:{server.server_port}/v1",
                                                api_key="test-only", model="fixture"),
                                 "ja", should_cancel=cancel.is_set)
            try:
                assert received.wait(3)
                cancel.set()
                with pytest.raises(ai.LlmCancelled):
                    future.result(timeout=1.5)
            finally:
                release.set()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(2)


@pytest.mark.parametrize("changed", ["language", "input", "version", "legacy", "none"])
def test_generation_only_reuses_cache_with_matching_provenance(monkeypatch, changed):
    transcript = [TranscriptSegment(start=0, end=2, text="Source sentence")]
    cached = ai.stamp_study_cache(material(), "Lesson", transcript, "zh-CN")
    cached.translated_title = "旧中文标题"
    cached.context_summary = "旧中文上下文"
    cached.translated_transcript = [TranscriptSegment(start=0, end=2, text="旧中文字幕")]
    language = "ja" if changed == "language" else "zh-CN"
    if changed == "input":
        transcript = [TranscriptSegment(start=0, end=2, text="New source sentence")]
    if changed == "version":
        cached.generation_version = -1
    if changed == "legacy":
        cached.input_fingerprint = None
    captured = {}

    def generate(*args):
        captured["translation"], captured["context"], captured["title"] = args[8:11]
        return material()

    monkeypatch.setattr(ai, "_generate_study_material_impl", generate)
    result = ai.generate_study_material("Lesson", transcript, None, language, existing_study=cached)
    if changed == "none":
        assert captured["translation"] == cached.translated_transcript
        assert captured["title"] == cached.translated_title
        assert captured["context"] == cached.context_summary
    else:
        assert captured == {"translation": None, "context": None, "title": None}
    assert ai.study_cache_matches(result, "Lesson", transcript, language)


def test_failed_settings_write_keeps_memory_and_disk_unchanged(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    env = tmp_path / "settings.env"
    env.write_text("UNCHANGED=yes\n", encoding="utf-8")
    original = make_client(tmp_path, env_path=env)
    client = TestClient(original.app, raise_server_exceptions=False, base_url="http://127.0.0.1")
    before = client.get("/api/settings/asr-cache").json()

    def fail_write(*_):
        raise OSError("Disk full")

    monkeypatch.setattr(app_module, "_write_model_env", fail_write)
    result = client.put("/api/settings/asr-cache", json={"auto_cleanup_enabled": False})
    assert result.status_code >= 400
    assert client.get("/api/settings/asr-cache").json() == before
    assert env.read_text(encoding="utf-8") == "UNCHANGED=yes\n"


def test_model_list_does_not_send_stored_key_to_another_service(tmp_path, monkeypatch):
    from course_navigator.config import Settings
    import httpx

    client = make_client(tmp_path, settings=Settings(data_dir=tmp_path, model_profiles=[{
        "id": "saved", "name": "Saved", "base_url": "https://trusted.example/v1",
        "model": "example", "api_key": "test-saved-key"}]))
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("headers", {})))
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(app_module.httpx, "get", get)
    response = client.post("/api/settings/models", json={
        "base_url": "https://untrusted.example/v1", "profile_id": "saved"})
    assert response.status_code == 400
    assert calls == []
    response = client.post("/api/settings/models", json={
        "base_url": "https://trusted.example/v1/", "profile_id": "saved"})
    assert response.status_code == 200
    assert calls[-1][1]["Authorization"] == "Bearer test-saved-key"


def test_active_asr_chunks_survive_cache_cleanup(tmp_path):
    from course_navigator import artifacts

    active = tmp_path / "subtitles" / "active"
    inactive = tmp_path / "subtitles" / "inactive"
    active.mkdir(parents=True)
    inactive.mkdir()
    for name in ["current.wav", "next.wav"]:
        (active / name).write_bytes(b"audio")
    (inactive / "old.wav").write_bytes(b"old")
    with artifacts.lease(active):
        assert app_module._cleanup_asr_cache(tmp_path) == 3
        assert (active / "current.wav").exists()
        assert (active / "next.wav").exists()
    assert app_module._cleanup_asr_cache(tmp_path) == 10


@pytest.mark.parametrize("contents", ["{not json", "[]", "123", "null", '{"id":"wrong"}'])
def test_corrupt_record_is_reported_without_hiding_healthy_courses(tmp_path, contents):
    client = make_client(tmp_path)
    client.post("/api/preview", json={"url": URL})
    broken = tmp_path / "items" / "broken.json"
    broken.write_text(contents, encoding="utf-8")
    assert len(client.get("/api/items").json()) == 1
    assert "broken.json" in client.get("/api/library-errors").json()
    assert broken.read_text(encoding="utf-8") == contents
    assert client.get("/api/library-errors/broken.json").content.decode() == contents
    restarted = make_client(tmp_path)
    assert len(restarted.get("/api/items").json()) == 1


def test_completed_jobs_are_bounded_but_running_jobs_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "MAX_RETAINED_JOBS", 2)
    monkeypatch.setattr(app_module, "generate_study_material", lambda **_: material())
    client = make_client(tmp_path)
    item = client.post("/api/extract", json={"url": URL}).json()
    ids = []
    for _ in range(4):
        job = client.post(f"/api/items/{item['id']}/study-jobs").json()
        ids.append(job["job_id"])
        assert terminal(client, ids[-1])["status"] == "succeeded"
    assert client.get(f"/api/jobs/{ids[0]}").status_code == 404
    assert client.get(f"/api/jobs/{ids[-1]}").status_code == 200


def test_full_queue_rejects_new_work_without_interrupting_active_job(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "MAX_ACTIVE_JOBS", 1)
    started, release = Event(), Event()

    def generate(**_):
        started.set()
        assert release.wait(3)
        return material()

    monkeypatch.setattr(app_module, "generate_study_material", generate)
    client = make_client(tmp_path)
    item = client.post("/api/extract", json={"url": URL}).json()
    first = client.post(f"/api/items/{item['id']}/study-jobs").json()
    try:
        assert started.wait(2)
        rejected = client.post(f"/api/items/{item['id']}/study-jobs")
        assert rejected.status_code == 429
        assert client.get(f"/api/jobs/{first['job_id']}").json()["status"] == "running"
    finally:
        release.set()
    assert terminal(client, first["job_id"])["status"] == "succeeded"


def test_deferred_artifact_cleanup_never_removes_a_new_operation(tmp_path):
    from course_navigator import artifacts

    old, new = tmp_path / "course" / "old-instance", tmp_path / "course" / "new-instance"
    with artifacts.lease(old):
        old.mkdir(parents=True)
        (old / "next.wav").write_bytes(b"old audio")
        artifacts.remove_tree(tmp_path / "course")
        assert (old / "next.wav").exists()
        new.mkdir()
        (new / "next.wav").write_bytes(b"new audio")
    assert not old.exists()
    assert (new / "next.wav").read_bytes() == b"new audio"


def test_partial_generation_writes_course_only_at_final_commit(tmp_path, monkeypatch):
    from course_navigator.library import CourseLibrary

    client = make_client(tmp_path)
    item = client.post("/api/extract", json={"url": URL}).json()
    writes = []
    original_write = CourseLibrary._write

    def record_write(self, course):
        writes.append(course.id)
        original_write(self, course)

    def generate(**kwargs):
        for _ in range(10):
            kwargs["partial_study"](material())
        assert writes == []
        assert CourseLibrary(tmp_path).get(item["id"]).study is None
        return material()

    monkeypatch.setattr(CourseLibrary, "_write", record_write)
    monkeypatch.setattr(app_module, "generate_study_material", generate)
    job = client.post(f"/api/items/{item['id']}/study-jobs").json()
    assert terminal(client, job["job_id"])["status"] == "succeeded"
    assert writes == [item["id"]]
