"""Cross-operation regressions between extraction, jobs and edits."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

import course_navigator.app as app_module
import course_navigator.ytdlp as ytdlp
from course_navigator.library import CourseLibrary
from course_navigator.models import TranscriptSegment
from test_app import FakeRunner, make_client
from test_data_integrity import URL, material, terminal


@pytest.mark.parametrize("route", ["extract", "extract-jobs"])
@pytest.mark.parametrize("window", ["metadata", "subtitles"])
@pytest.mark.parametrize("edit", ["transcript", "title"])
def test_extraction_keeps_user_edits_across_entire_operation(tmp_path, route, window, edit):
    started, release = Event(), Event()

    class Paused(FakeRunner):
        armed = False

        def fetch_metadata(self, request):
            if self.armed and window == "metadata":
                started.set()
                assert release.wait(5)
            return super().fetch_metadata(request)

        def extract_subtitles(self, *args, **kwargs):
            if self.armed and window == "subtitles":
                started.set()
                assert release.wait(5)
            return super().extract_subtitles(*args, **kwargs)

    runner = Paused()
    client = make_client(tmp_path, runner=runner)
    item = client.post("/api/preview", json={"url": URL}).json()
    runner.armed = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(client.post, f"/api/{route}", json={"url": URL})
        try:
            assert started.wait(3)
            if edit == "transcript":
                response = client.put(f"/api/items/{item['id']}/transcript", json={
                    "transcript": [{"start": 0, "end": 3, "text": "USER MANUAL EDIT"}]})
            else:
                response = client.patch(f"/api/items/{item['id']}", json={"title": "My edited title"})
            assert response.status_code == 200
        finally:
            release.set()
        response = result.result(timeout=3)
    if route == "extract-jobs":
        status = terminal(client, response.json()["job_id"])["status"]
        assert status == ("failed" if edit == "transcript" else "succeeded")
    else:
        assert response.status_code == (409 if edit == "transcript" else 200)
    saved = client.get(f"/api/items/{item['id']}").json()
    assert saved["transcript"][0]["text"] == ("USER MANUAL EDIT" if edit == "transcript" else "Opening idea.")
    if edit == "title":
        assert saved["title"] == "My edited title"


@pytest.mark.parametrize("task", ["study", "translation", "extract"])
def test_caching_same_video_does_not_invalidate_text_work(tmp_path, monkeypatch, task):
    started, release = Event(), Event()

    def generate(**kwargs):
        started.set()
        assert release.wait(5)
        if task == "study":
            result = material()
            kwargs["partial_study"](result)
            return result
        segments = [s.model_copy(update={"text": "课程译文"}) for s in kwargs["transcript"]]
        kwargs["partial_translation"](segments)
        return segments

    class Paused(FakeRunner):
        armed = False

        def extract_subtitles(self, *args, **kwargs):
            if self.armed:
                started.set()
                assert release.wait(5)
            return super().extract_subtitles(*args, **kwargs)

    monkeypatch.setattr(app_module, "generate_study_material", generate)
    monkeypatch.setattr(app_module, "translate_transcript_material", generate)
    runner = Paused()
    client = make_client(tmp_path, runner=runner)
    item = client.post("/api/extract", json={"url": URL}).json()
    runner.armed = True
    job = (client.post("/api/extract-jobs", json={"url": URL}) if task == "extract"
           else client.post(f"/api/items/{item['id']}/{task}-jobs")).json()
    try:
        assert started.wait(3)
        cached = client.post(f"/api/items/{item['id']}/download", json={"url": URL})
        assert cached.status_code == 200
    finally:
        release.set()
    assert terminal(client, job["job_id"])["status"] == "succeeded"
    current = client.get(f"/api/items/{item['id']}").json()
    assert current["local_video_path"] and current["video_source_type"] == "workspace"
    assert current["transcript"]
    if task != "extract":
        assert current["study"] is not None


@pytest.mark.parametrize("route", ["download", "download-jobs"])
def test_transcript_edit_does_not_discard_same_source_download(tmp_path, route):
    started, release = Event(), Event()

    class Paused(FakeRunner):
        def download_video(self, *args, **kwargs):
            started.set()
            assert release.wait(5)
            return super().download_video(*args, **kwargs)

    client = make_client(tmp_path, runner=Paused())
    item = client.post("/api/extract", json={"url": URL}).json()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(client.post, f"/api/items/{item['id']}/{route}", json={"url": URL})
        try:
            assert started.wait(3)
            assert client.put(f"/api/items/{item['id']}/transcript", json={
                "transcript": [{"start": 0, "end": 3, "text": "USER MANUAL EDIT"}]}).status_code == 200
        finally:
            release.set()
        response = result.result(timeout=3)
    assert response.status_code == 200
    if route == "download-jobs":
        assert terminal(client, response.json()["job_id"])["status"] == "succeeded"
    current = client.get(f"/api/items/{item['id']}").json()
    assert current["transcript"][0]["text"] == "USER MANUAL EDIT"
    assert current["local_video_path"]


@pytest.mark.parametrize("field", ["uploader", "stream_url"])
@pytest.mark.parametrize("task", ["study", "translation"])
def test_generation_and_cache_use_same_metadata_inputs(tmp_path, monkeypatch, field, task):
    started, release = Event(), Event()

    class Changing(FakeRunner):
        changed = False

        def fetch_metadata(self, request):
            metadata = super().fetch_metadata(request)
            if self.changed:
                setattr(metadata, field, "Teacher B" if field == "uploader" else "https://cdn.example.com/new.m3u8")
            return metadata

    def generate(**kwargs):
        started.set()
        assert release.wait(5)
        if task == "study":
            return material()
        return [s.model_copy(update={"text": "课程译文"}) for s in kwargs["transcript"]]

    monkeypatch.setattr(app_module, "generate_study_material", generate)
    monkeypatch.setattr(app_module, "translate_transcript_material", generate)
    runner = Changing()
    client = make_client(tmp_path, runner=runner)
    item = client.post("/api/extract", json={"url": URL}).json()
    job = client.post(f"/api/items/{item['id']}/{task}-jobs").json()
    try:
        assert started.wait(3)
        runner.changed = True
        assert client.post(f"/api/items/{item['id']}/playback-source?force=true").status_code == 200
    finally:
        release.set()
    assert terminal(client, job["job_id"])["status"] == ("failed" if field == "uploader" else "succeeded")
    current = client.get(f"/api/items/{item['id']}").json()
    assert (current["study"] is None) == (field == "uploader")


@pytest.mark.parametrize("request_language", ["en", "auto"])
@pytest.mark.parametrize("track_language", ["zh", "en", None])
def test_hls_extraction_records_actual_track_language(tmp_path, monkeypatch, request_language, track_language):
    class HlsRunner(ytdlp.YtDlpRunner):
        fetch_metadata = FakeRunner.fetch_metadata

    def download(url):
        if url.endswith(".m3u8"):
            language = f',LANGUAGE="{track_language}"' if track_language else ""
            return f'#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,NAME="Track"{language},URI="track.vtt"\n'
        return "WEBVTT\n\n00:00:00.000 --> 00:00:04.000\n" + ("Hello world" if track_language == "en" else "这是中文字幕") + "\n"

    monkeypatch.setattr(ytdlp, "_run_with_browser_cookie_retry", lambda command, request, cache:
                        (SimpleNamespace(returncode=0, stderr=""), request))
    monkeypatch.setattr(ytdlp, "_download_text", download)
    client = make_client(tmp_path, runner=HlsRunner(binary="yt-dlp"))
    result = client.post("/api/extract", json={"url": URL, "language": request_language})
    assert result.status_code == 200
    item = result.json()
    assert item["transcript_language"] == track_language
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "en"}).json()
    assert terminal(client, job["job_id"])["status"] == ("succeeded" if track_language == "en" else "failed")


@pytest.mark.parametrize("port", ["abc", "99999"])
def test_bad_remote_binding_is_rejected_before_persistence(tmp_path, port):
    client = make_client(tmp_path)
    item = client.post("/api/preview", json={"url": URL}).json()
    response = client.post(f"/api/items/{item['id']}/video-source", json={
        "source_type": "remote", "url": f"https://fixture.test:{port}/video"})
    assert response.status_code in {400, 422}
    assert client.get(f"/api/items/{item['id']}").json()["source_url"] == URL


@pytest.mark.parametrize("route", ["preview", "extract", "extract-jobs"])
@pytest.mark.parametrize("port", ["abc", "99999"])
def test_legacy_bad_url_does_not_poison_unrelated_courses(tmp_path, route, port):
    client = make_client(tmp_path)
    old = client.post("/api/preview", json={"url": URL}).json()
    library = CourseLibrary(tmp_path)
    item = library.get(old["id"])
    library.save(item.model_copy(update={"source_url": f"https://fixture.test:{port}/video"}))
    response = client.post(f"/api/{route}", json={"url": "https://healthy.test/video"})
    assert response.status_code == 200
    if route == "extract-jobs":
        assert terminal(client, response.json()["job_id"])["status"] == "succeeded"
    assert client.get(f"/api/items/{old['id']}").status_code == 200
    assert client.delete(f"/api/items/{old['id']}").status_code == 200


def test_playback_refresh_uses_latest_transcript_duration(tmp_path):
    started, release = Event(), Event()

    class Paused(FakeRunner):
        armed = False

        def fetch_metadata(self, request):
            if self.armed:
                started.set()
                assert release.wait(5)
            return super().fetch_metadata(request).model_copy(update={"duration": None})

    runner = Paused()
    client = make_client(tmp_path, runner=runner)
    item = client.post("/api/preview", json={"url": URL}).json()
    client.put(f"/api/items/{item['id']}/transcript", json={
        "transcript": [{"start": 0, "end": 10, "text": "Old subtitle"}]})
    runner.armed = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f"/api/items/{item['id']}/playback-source?force=true")
        try:
            assert started.wait(3)
            assert client.put(f"/api/items/{item['id']}/transcript", json={
                "transcript": [{"start": 0, "end": 60, "text": "Updated subtitle"}]}).status_code == 200
        finally:
            release.set()
        assert future.result(timeout=3).status_code == 200
    current = client.get(f"/api/items/{item['id']}").json()
    assert current["transcript"][0]["end"] == 60
    assert current["duration"] == 60


@pytest.mark.parametrize("url", ["https://[2001:db8::1]:8443/video", "ytsearch:lesson", "BaW_jenozKc",
                                "//www.youtube.com/watch?v=BaW_jenozKc", "youtu.be/BaW_jenozKc"])
def test_url_validation_keeps_existing_extractor_input_forms(tmp_path, url):
    client = make_client(tmp_path)
    response = client.post("/api/preview", json={"url": url})
    assert response.status_code == 200
    assert response.json()["source_url"] == url


@pytest.mark.parametrize("change", ["metadata", "source"])
def test_playback_refresh_still_rejects_overlapping_changes(tmp_path, change):
    started, release = Event(), Event()

    class Paused(FakeRunner):
        armed = False

        def fetch_metadata(self, request):
            if self.armed:
                self.armed = False
                started.set()
                assert release.wait(5)
                return super().fetch_metadata(request).model_copy(update={"stream_url": "https://cdn.test/old.m3u8"})
            return super().fetch_metadata(request).model_copy(update={"stream_url": "https://cdn.test/new.m3u8"})

    runner = Paused()
    client = make_client(tmp_path, runner=runner)
    item = client.post("/api/preview", json={"url": URL}).json()
    # A different initial value makes the two simultaneous refreshes overlap.
    library = CourseLibrary(tmp_path)
    initial = library.get(item["id"])
    initial.metadata.stream_url = "https://cdn.test/initial.m3u8"
    library.save(initial)
    runner.armed = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f"/api/items/{item['id']}/playback-source?force=true")
        try:
            assert started.wait(3)
            if change == "metadata":
                response = client.post(f"/api/items/{item['id']}/playback-source?force=true")
            else:
                response = client.post(f"/api/items/{item['id']}/video-source", json={
                    "source_type": "remote", "url": "https://new-source.test/video"})
            assert response.status_code == 200
        finally:
            release.set()
        assert future.result(timeout=3).status_code == 409
    current = client.get(f"/api/items/{item['id']}").json()
    if change == "metadata":
        assert current["metadata"]["stream_url"] == "https://cdn.test/new.m3u8"
    else:
        assert current["source_url"] == "https://new-source.test/video"


@pytest.mark.parametrize("edit", ["transcript", "title"])
def test_metadata_resolution_of_unknown_alias_preserves_starting_inputs(tmp_path, edit):
    started, release = Event(), Event()
    first_url, alias = "https://fixture.test/first", "https://fixture.test/alias"

    class Paused(FakeRunner):
        def fetch_metadata(self, request):
            if request.url == alias:
                started.set()
                assert release.wait(5)
            return super().fetch_metadata(request)

    client = make_client(tmp_path, runner=Paused())
    item = client.post("/api/preview", json={"url": first_url}).json()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/extract", json={"url": alias})
        try:
            assert started.wait(3)
            if edit == "transcript":
                response = client.put(f"/api/items/{item['id']}/transcript", json={
                    "transcript": [{"start": 0, "end": 4, "text": "USER MANUAL EDIT"}]})
            else:
                response = client.patch(f"/api/items/{item['id']}", json={"title": "My edited title"})
            assert response.status_code == 200
        finally:
            release.set()
        assert future.result(timeout=3).status_code == (409 if edit == "transcript" else 200)
    current = client.get(f"/api/items/{item['id']}").json()
    assert current["instance_id"] == item["instance_id"]
    assert current["transcript"][0]["text"] == ("USER MANUAL EDIT" if edit == "transcript" else "Opening idea.")
    assert len(client.get("/api/items").json()) == 1


@pytest.mark.parametrize("suffix,language", [("en", "en"), ("ai-zh", "zh"), ("zh-CN", "zh-CN"), (None, None)])
def test_regular_subtitle_files_supply_actual_language(tmp_path, monkeypatch, suffix, language):
    class FileRunner(ytdlp.YtDlpRunner):
        fetch_metadata = FakeRunner.fetch_metadata

    def run(command, request, cache):
        args = command(request)
        template = args[args.index("--output") + 1]
        target = Path(template).parent / (f"abc123.{suffix}.vtt" if suffix else "abc123.vtt")
        target.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:04.000\nA subtitle\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr=""), request

    monkeypatch.setattr(ytdlp, "_run_with_browser_cookie_retry", run)
    client = make_client(tmp_path, runner=FileRunner(binary="yt-dlp"))
    response = client.post("/api/extract", json={"url": URL, "language": "en"})
    assert response.status_code == 200
    assert response.json()["transcript_language"] == language
