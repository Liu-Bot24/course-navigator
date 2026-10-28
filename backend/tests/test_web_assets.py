"""The API process also serves the built frontend for the desktop launcher."""

from fastapi.testclient import TestClient

from course_navigator.app import create_app
from course_navigator.config import Settings
from test_app import FakeRunner


def web_client(tmp_path, dist):
    data = tmp_path / "data"
    return TestClient(create_app(data_dir=data, runner=FakeRunner(), settings=Settings(data_dir=data),
                                 env_path=None, web_dist_dir=dist), base_url="http://127.0.0.1")


def test_built_pages_are_served_next_to_the_api(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>Course Navigator</title>", encoding="utf-8")
    (dist / "assets" / "app-1a2b.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    client = web_client(tmp_path, dist)

    page = client.get("/")
    assert page.status_code == 200
    assert "<title>Course Navigator</title>" in page.text
    assert page.headers["cache-control"] == "no-cache"
    asset = client.get("/assets/app-1a2b.js")
    assert asset.status_code == 200
    assert "cache-control" not in asset.headers
    # API routes still win, and unknown API paths stay JSON 404s.
    assert client.get("/api/health").json()["name"] == "Course Navigator"
    missing = client.get("/api/does-not-exist")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}
    assert client.get("/../secret.txt").status_code == 404
    assert client.get("/%2e%2e/secret.txt").status_code == 404


def test_without_a_build_only_the_api_is_served(tmp_path):
    client = web_client(tmp_path, tmp_path / "missing-dist")

    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 404
