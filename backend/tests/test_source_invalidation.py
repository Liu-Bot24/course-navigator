"""Source aliases, saved service keys and cancellation of in-flight requests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from test_app import FakeRunner, make_client
from test_data_integrity import URL, terminal


@pytest.mark.parametrize("route", ["preview", "extract", "extract-jobs"])
@pytest.mark.parametrize("reimport", [False, True])
@pytest.mark.parametrize("pending_metadata", [False, True])
def test_deleted_source_alias_cannot_return_after_metadata(tmp_path, route, reimport, pending_metadata):
    started, release = Event(), Event()
    alias = "https://youtu.be/abc123"

    class PausedMetadata(FakeRunner):
        def fetch_metadata(self, request):
            if request.url == alias:
                started.set()
                assert release.wait(5)
            return super().fetch_metadata(request)

    client = make_client(tmp_path, runner=PausedMetadata())
    old = client.post("/api/preview", json={"url": URL if not pending_metadata else "https://www.youtube.com/watch?v=old"}).json()
    if pending_metadata:
        assert client.post(f"/api/items/{old['id']}/video-source", json={"source_type": "remote", "url": URL}).status_code == 200
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(client.post, f"/api/{route}", json={"url": alias})
        try:
            assert started.wait(2)
            assert client.delete(f"/api/items/{old['id']}").status_code == 200
            if reimport:
                new = client.post("/api/preview", json={"url": URL}).json()
        finally:
            release.set()
        response = work.result(timeout=4)
    if route == "extract-jobs":
        assert terminal(client, response.json()["job_id"])["status"] in {"failed", "cancelled"}
    else:
        assert response.status_code == 409
    items = client.get("/api/items").json()
    assert len(items) == int(reimport)
    if reimport:
        assert items[0]["instance_id"] == new["instance_id"]
        assert items[0]["transcript"] == []
    # A fresh operation is allowed after deletion.
    assert client.post("/api/extract", json={"url": alias}).status_code == 200


@pytest.mark.parametrize("service,slot,suffix", [
    ("online-asr", "custom", "/audio/transcriptions"),
    ("asr-search", "firecrawl", "/search"),
])
@pytest.mark.parametrize("equivalent", [False, True])
def test_saved_service_key_follows_actual_endpoint(tmp_path, service, slot, suffix, equivalent):
    client = make_client(tmp_path)
    base = "https://fixture.test/v1"
    seeded = client.put(f"/api/settings/{service}", json={slot: {"base_url": base, "api_key": "test-only-key"}})
    assert seeded.status_code == 200
    changed = base + (suffix if equivalent else "/messages")
    response = client.put(f"/api/settings/{service}", json={slot: {"base_url": changed}})
    assert response.status_code == 200
    assert response.json()[slot]["has_api_key"] is equivalent


@pytest.mark.parametrize("kind", ["llm", "asr", "search"])
@pytest.mark.parametrize("waiting_for", ["headers", "body"])
def test_cancel_real_http_wait_leaves_other_requests_usable(kind, waiting_for):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    import io
    import httpx
    from course_navigator import ai, asr, online_asr
    from course_navigator.ytdlp import YtDlpCancelled

    received, release, cancel = Event(), Event(), Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                if self.path == "/slow":
                    if waiting_for == "body":
                        self.send_response(200)
                        self.send_header("Content-Length", "2")
                        self.end_headers()
                        self.wfile.flush()
                    received.set()
                    release.wait(5)
                if self.path != "/slow" or waiting_for == "headers":
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                self.wfile.write(b"{}")
            except OSError:
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def post(path, callback):
        if kind == "llm":
            return ai._post_llm_request(base + path, headers={}, payload={}, timeout=httpx.Timeout(10), should_cancel=callback)
        if kind == "search":
            return asr._post_search_request(base + path, headers={}, payload={}, timeout=10, should_cancel=callback)
        return online_asr._post_transcription_request(base + path, "test-only", {},
                                                     {"file": ("audio.mp3", io.BytesIO(b"test"), "audio/mpeg")}, callback)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(post, "/slow", cancel.is_set)
            try:
                assert received.wait(3)
                other = pool.submit(post, "/fast", lambda: False)
                cancel.set()
                with pytest.raises(YtDlpCancelled if kind == "asr" else ai.LlmCancelled):
                    future.result(timeout=1.5)
                assert not release.is_set()
                assert other.result(timeout=2).json() == {}
            finally:
                release.set()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_source_invalidation_is_retained_until_oldest_request_finishes():
    from course_navigator.source_operations import SourceOperations
    from course_navigator.library import CourseConflict
    operations = SourceOperations()
    old = operations.begin()
    operations.invalidate({"source"})
    new = operations.begin()
    operations.check(new, {"source"})
    operations.finish(new)
    with pytest.raises(CourseConflict):
        operations.check(old, {"source"})
    operations.check(old, {"different-source"})
    operations.finish(old)
    assert not operations._invalidations
    assert not operations._active
