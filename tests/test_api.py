from fastapi.testclient import TestClient


def test_upload_requires_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/upload", data={"book": "코스모스"}, files={"file": ("a.txt", b"hi")})
    assert r.status_code == 401


def test_upload_ok(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/upload", headers={"X-Brain-Token": "test-token"},
                   data={"book": "코스모스"}, files={"file": ("a.txt", "우주".encode())})
        assert r.status_code == 200 and r.json()["slug"] == "코스모스"
        assert c.get("/books").json()[0]["title"] == "코스모스"


def test_health(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_root_redirects_to_site(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/site/index.html"


def test_search_requires_no_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/search", params={"q": "nope"})
    assert r.status_code == 200
    assert r.json() == []


def test_process_requires_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/books/코스모스/process")
    assert r.status_code == 401
