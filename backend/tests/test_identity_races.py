"""Endpoint rules, source identity upgrades and races around them."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
from threading import Event

import httpx
import pytest

from course_navigator import artifacts
from course_navigator.config import Settings
from course_navigator.models import TranscriptSegment
from test_app import FakeRunner, FakeLocalVideoRunner, make_client
from test_data_integrity import URL, terminal


def test_explicit_anthropic_message_endpoint_keeps_its_exact_path(monkeypatch):
    from course_navigator.ai import LlmProvider, _chat_text
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"content": [{"type": "text", "text": "ok"}]})

    monkeypatch.setattr(httpx, "post", post)
    endpoint = "https://fixture.test/anthropic/messages"
    result = _chat_text(LlmProvider(base_url=endpoint, api_key="test-only", model="fixture", provider_type="anthropic"),
                        [{"role": "user", "content": "Hello"}], temperature=0, max_tokens=10, timeout=5)
    assert result == "ok"
    assert calls == [endpoint]


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("address", ["full_endpoint", "model_list", "different_protocol"])
def test_profile_edit_and_generation_share_endpoint_rules(tmp_path, monkeypatch, provider, address):
    calls = []
    base = "https://fixture.test/v1"
    endpoint = "/messages" if provider == "anthropic" else "/chat/completions"
    equivalent = address != "different_protocol"
    changed = base + ("/models" if address == "model_list" else endpoint if equivalent
                      else ("/chat/completions" if provider == "anthropic" else "/messages"))
    profile = {"id": "p", "name": "P", "provider_type": provider, "base_url": base,
               "model": "fixture", "api_key": "test-saved-key"}
    slots = {name: "p" for name in ("translation_model_id", "learning_model_id", "global_model_id", "asr_model_id")}
    client = make_client(tmp_path, settings=Settings(data_dir=tmp_path, model_profiles=[profile], **slots))

    async def post(self, url, **kwargs):
        calls.append((str(url), kwargs["headers"]))
        body = kwargs["json"]
        system = body.get("system") or body["messages"][0]["content"]
        if "translated_transcript" in system:
            payload = {"translated_transcript": [{"start": 0, "end": 4, "text": "课程译文。"}]}
        elif "translated_title" in system:
            payload = {"translated_title": "课程"}
        else:
            payload = {"summary": "课程摘要。"}
        content = json.dumps(payload, ensure_ascii=False)
        response = ({"content": [{"type": "text", "text": content}]} if provider == "anthropic"
                    else {"choices": [{"message": {"content": content}}]})
        return httpx.Response(200, request=httpx.Request("POST", url), json=response)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    probes = []

    def get(url, **kwargs):
        probes.append((str(url), kwargs["headers"]))
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{"id": "fixture"}]})

    monkeypatch.setattr(httpx, "get", get)
    probe = client.post("/api/settings/models", json={"profile_id": "p", "provider_type": provider, "base_url": changed})
    assert probe.status_code == (200 if equivalent else 400)
    if equivalent:
        assert probes[0][0] == base + "/models"
    else:
        assert probes == []
    updated = {**profile, "base_url": changed}
    updated.pop("api_key")
    response = client.put("/api/settings/model", json={"profiles": [updated], **slots})
    assert response.status_code == 200
    item = client.post("/api/preview", json={"url": URL}).json()
    client.put(f"/api/items/{item['id']}/transcript", json={
        "transcript": [{"start": 0, "end": 4, "text": "A course subtitle."}], "language": "en"})
    job = client.post(f"/api/items/{item['id']}/translation-jobs", json={"output_language": "zh-CN"}).json()
    assert terminal(client, job["job_id"])["status"] == ("succeeded" if equivalent else "failed")
    if equivalent:
        assert calls
        assert all(url == base + endpoint for url, _ in calls)
        assert all(headers.get("x-api-key") == "test-saved-key" if provider == "anthropic"
                   else headers.get("Authorization") == "Bearer test-saved-key" for _, headers in calls)
    else:
        assert calls == []


@pytest.mark.parametrize("route", ["preview", "extract", "extract-jobs"])
@pytest.mark.parametrize("initial_id,initial_extractor", [
    ("unknown", "youtube"), ("abc123", "generic"), ("abc123", "unknown"), ("abc123", ""),
])
def test_nonempty_unresolved_metadata_upgrades_in_same_instance(tmp_path, route, initial_id, initial_extractor):
    class Resolving(FakeRunner):
        unresolved = True

        def fetch_metadata(self, request):
            result = super().fetch_metadata(request)
            if self.unresolved:
                result.id, result.extractor = initial_id, initial_extractor
            return result

    runner = Resolving()
    client = make_client(tmp_path, runner=runner)
    first = client.post("/api/preview", json={"url": URL}).json()
    runner.unresolved = False
    result = client.post(f"/api/{route}", json={"url": URL})
    assert result.status_code == 200
    if route == "extract-jobs":
        assert terminal(client, result.json()["job_id"])["status"] == "succeeded"
    current = client.get(f"/api/items/{first['id']}").json()
    assert current["instance_id"] == first["instance_id"]
    assert current["metadata"]["id"] == "abc123"
    assert current["metadata"]["extractor"] == "youtube"
    assert len(client.get("/api/items").json()) == 1


def test_different_stable_platform_identity_is_not_upgraded_by_url(tmp_path):
    class ChangedId(FakeRunner):
        platform_id = "abc123"

        def fetch_metadata(self, request):
            result = super().fetch_metadata(request)
            result.id = self.platform_id
            return result

    runner = ChangedId()
    client = make_client(tmp_path, runner=runner)
    first = client.post("/api/preview", json={"url": URL}).json()
    runner.platform_id = "different-video"
    assert client.post("/api/preview", json={"url": URL}).status_code == 409
    assert client.get(f"/api/items/{first['id']}").json()["metadata"]["id"] == "abc123"


@pytest.mark.parametrize("change", ["delete", "rebind"])
def test_unresolved_identity_upgrade_rejects_intervening_source_change(tmp_path, change):
    started, release = Event(), Event()

    class Resolving(FakeRunner):
        unresolved = True

        def fetch_metadata(self, request):
            result = super().fetch_metadata(request)
            if self.unresolved:
                result.id = "unknown"
            else:
                started.set()
                assert release.wait(5)
            return result

    runner = Resolving()
    client = make_client(tmp_path, runner=runner)
    first = client.post("/api/preview", json={"url": URL}).json()
    runner.unresolved = False
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/extract", json={"url": URL})
        try:
            assert started.wait(2)
            if change == "delete":
                assert client.delete(f"/api/items/{first['id']}").status_code == 200
            else:
                assert client.post(f"/api/items/{first['id']}/video-source", json={
                    "source_type": "remote", "url": "https://www.youtube.com/watch?v=other"}).status_code == 200
        finally:
            release.set()
        assert future.result(timeout=3).status_code == 409
    if change == "delete":
        assert client.get("/api/items").json() == []
    else:
        current = client.get(f"/api/items/{first['id']}").json()
        assert current["source_url"].endswith("v=other")
        assert current["transcript"] == []


def test_deleted_external_extraction_cleans_directory_created_after_deletion(tmp_path, monkeypatch):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"external original")
    before_lease, release = Event(), Event()
    operation_paths = []

    class AudioRunner(FakeLocalVideoRunner):
        def extract_asr_from_file(self, video_path, target_dir, item_id, **kwargs):
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "audio.wav").write_bytes(b"old task audio")
            return [TranscriptSegment(start=0, end=2, text="Old video subtitle")]

    client = make_client(tmp_path / "data", runner=AudioRunner())
    old = client.post("/api/local-video-paths", json={"paths": [str(video)], "mode": "external"}).json()[0]
    original_lease = artifacts.lease

    @contextmanager
    def paused_lease(path, **kwargs):
        if old["instance_id"] in Path(path).parts:
            operation_paths.append(Path(path))
            before_lease.set()
            assert release.wait(5)
        with original_lease(path, **kwargs):
            yield path

    monkeypatch.setattr(artifacts, "lease", paused_lease)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/extract", json={"url": old["source_url"], "subtitle_source": "asr"})
        try:
            assert before_lease.wait(2)
            assert client.delete(f"/api/items/{old['id']}").status_code == 200
            new = client.post("/api/local-video-paths", json={"paths": [str(video)], "mode": "external"}).json()[0]
        finally:
            release.set()
        assert future.result(timeout=3).status_code == 409
    assert operation_paths and all(not path.exists() for path in operation_paths)
    assert client.get(f"/api/items/{new['id']}").json()["transcript"] == []
    assert video.read_bytes() == b"external original"
