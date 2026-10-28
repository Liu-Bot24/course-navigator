"""Malformed legacy URL handling must cover display and metadata aliases."""
import pytest

from course_navigator.library import CourseLibrary
from test_app import make_client
from test_data_integrity import URL, terminal


@pytest.mark.parametrize("bad_url", ["https://[2001:db8::1/video", "https://fixture.test\uff0fextra/video"])
@pytest.mark.parametrize("fallback", ["title", "collection"])
@pytest.mark.parametrize("read", ["item", "list"])
def test_unparseable_legacy_url_keeps_course_readable(tmp_path, bad_url, fallback, read):
    client = make_client(tmp_path)
    old = client.post("/api/preview", json={"url": URL}).json()
    library = CourseLibrary(tmp_path)
    item = library.get(old["id"]).model_copy(update={
        "source_url": bad_url, "title": "Saved course title", "custom_title": fallback == "collection",
        "collection_title": "Saved collection" if fallback == "title" else None,
    })
    library.save(item)
    original = (tmp_path / "items" / f"{item.id}.json").read_bytes()
    healthy = client.post("/api/preview", json={"url": "https://healthy.test/lesson"})
    assert healthy.status_code == 200
    response = client.get(f"/api/items/{item.id}" if read == "item" else "/api/items")
    assert response.status_code == 200
    actual = response.json() if read == "item" else next(saved for saved in response.json() if saved["id"] == item.id)
    assert actual["title"] == "Saved course title"
    assert actual["collection_title"] == item.collection_title
    assert actual["source_url"] == bad_url
    assert actual["instance_id"] == item.instance_id
    assert (tmp_path / "items" / f"{item.id}.json").read_bytes() == original
    assert client.delete(f"/api/items/{item.id}").status_code == 200
    assert client.get(f"/api/items/{healthy.json()['id']}").status_code == 200


@pytest.mark.parametrize("bad_url", ["https://fixture.test:abc/video", "https://fixture.test:99999/video",
                                   "https://[2001:db8::1/video"])
@pytest.mark.parametrize("route", ["preview", "extract", "extract-jobs"])
def test_invalid_legacy_source_cannot_match_through_metadata_alias(tmp_path, bad_url, route):
    client = make_client(tmp_path)
    old = client.post("/api/preview", json={"url": URL}).json()
    library = CourseLibrary(tmp_path)
    item = library.get(old["id"])
    assert item.metadata.webpage_url == URL
    library.save(item.model_copy(update={"source_url": bad_url}))
    original = (tmp_path / "items" / f"{item.id}.json").read_bytes()
    response = client.post(f"/api/{route}", json={"url": URL})
    assert response.status_code == 200
    if route == "extract-jobs":
        job = terminal(client, response.json()["job_id"])
        assert job["status"] == "succeeded"
        healthy = client.get(f"/api/items/{job['item_id']}").json()
    else:
        healthy = response.json()
    assert healthy["instance_id"] != item.instance_id
    assert healthy["id"] != item.id
    assert healthy["source_url"] == URL
    assert (tmp_path / "items" / f"{item.id}.json").read_bytes() == original
    assert len(client.get("/api/items").json()) == 2
    assert client.delete(f"/api/items/{item.id}").status_code == 200
    assert client.get(f"/api/items/{healthy['id']}").status_code == 200


@pytest.mark.parametrize("route", ["preview", "extract", "extract-jobs"])
def test_valid_source_still_matches_its_metadata_alias(tmp_path, route):
    client = make_client(tmp_path)
    old = client.post("/api/preview", json={"url": "https://fixture.test/original"}).json()
    library = CourseLibrary(tmp_path)
    item = library.get(old["id"])
    alias = "https://fixture.test/alias"
    item.metadata.webpage_url = alias
    library.save(item)
    response = client.post(f"/api/{route}", json={"url": alias})
    assert response.status_code == 200
    if route == "extract-jobs":
        assert terminal(client, response.json()["job_id"])["status"] == "succeeded"
    current = client.get(f"/api/items/{item.id}").json()
    assert current["instance_id"] == item.instance_id
    assert len(client.get("/api/items").json()) == 1
