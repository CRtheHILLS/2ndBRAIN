import pytest
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


def test_upload_sanitizes_path_traversal_filename(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/upload", headers={"X-Brain-Token": "test-token"},
                   data={"book": "코스모스"},
                   files={"file": ("../../evil.txt", b"pwned")})
    assert r.status_code == 200
    hits = list(data_dir.rglob("evil.txt"))
    assert len(hits) == 1
    assert data_dir in hits[0].parents
    assert hits[0].relative_to(data_dir).parts[0] == "books"
    assert not (data_dir.parent / "evil.txt").exists()


def test_upload_rejects_dotdot_filename(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/upload", headers={"X-Brain-Token": "test-token"},
                   data={"book": "코스모스"}, files={"file": ("..", b"x")})
    assert r.status_code == 400


def test_process_rejects_invalid_slug(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/books/../x/process", headers={"X-Brain-Token": "test-token"})
    assert r.status_code in (400, 404)


def test_robots_txt(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text == "User-agent: *\nDisallow: /"


def test_responses_have_no_index_header(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.headers["x-robots-tag"] == "noindex, nofollow"


def test_process_rejects_invalid_level(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/upload", headers={"X-Brain-Token": "test-token"},
               data={"book": "코스모스"}, files={"file": ("a.txt", "우주".encode())})
        r = c.post("/books/코스모스/process", params={"level": "고급"},
                   headers={"X-Brain-Token": "test-token"})
    assert r.status_code == 400


def test_process_rejects_book_with_no_material(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/books/코스모스/process", headers={"X-Brain-Token": "test-token"})
    assert r.status_code == 400
    assert "자료" in r.json()["detail"]


def test_process_returns_502_on_unparseable_llm_response(data_dir, monkeypatch):
    from api.main import app
    from brain import distill
    with TestClient(app) as c:
        c.post("/upload", headers={"X-Brain-Token": "test-token"},
               data={"book": "코스모스"}, files={"file": ("a.txt", "우주".encode())})
        monkeypatch.setattr(distill, "distill_book",
                             lambda slug: (_ for _ in ()).throw(ValueError("모델 응답 파싱 실패 — notes/.last-distill.txt 확인")))
        r = c.post("/books/코스모스/process", headers={"X-Brain-Token": "test-token"})
    assert r.status_code == 502


def test_casting_upload_requires_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/casting/upload", data={"model": "Alice"},
                   files={"file": ("face1.jpg", b"imgbytes")})
    assert r.status_code == 401


def test_casting_upload_list_img_roundtrip(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
                   data={"model": "Alice"},
                   files={"file": ("face1.jpg", b"imgbytes")})
        assert r.status_code == 200
        assert r.json() == {"model": "Alice", "file": "face1.jpg"}

        r = c.get("/casting/list")
        assert r.status_code == 200
        assert r.json() == {"models": [{"name": "Alice", "files": ["face1.jpg"]}], "picked": []}

        r = c.get("/casting/img/Alice/face1.jpg")
        assert r.status_code == 200
        assert r.content == b"imgbytes"
        assert r.headers["cache-control"] == "no-store"


def test_casting_list_empty(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/casting/list")
    assert r.status_code == 200
    assert r.json() == {"models": [], "picked": []}


def test_casting_img_path_traversal_returns_404(data_dir):
    # httpx normalizes literal ".." path segments before sending, so use
    # percent-encoded dots to exercise the server-side sanitization itself.
    from api.main import app
    with TestClient(app) as c:
        c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
               data={"model": "Alice"}, files={"file": ("face1.jpg", b"imgbytes")})
        r = c.get("/casting/img/Alice/%2e%2e")
        assert r.status_code in (400, 404)
        r = c.get("/casting/img/%2e%2e/face1.jpg")
        assert r.status_code in (400, 404)


def test_casting_delete_works_without_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
               data={"model": "Alice"}, files={"file": ("face1.jpg", b"imgbytes")})
        r = c.delete("/casting/Alice")
    assert r.status_code == 200


def test_casting_delete_model_removes_it(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
               data={"model": "Alice"}, files={"file": ("face1.jpg", b"imgbytes")})
        r = c.delete("/casting/Alice", headers={"X-Brain-Token": "test-token"})
        assert r.status_code == 200
        r = c.get("/casting/list")
        assert r.json() == {"models": [], "picked": []}


def test_casting_state_defaults(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/casting/state")
    assert r.status_code == 200
    assert r.json() == {"paused": False, "picked": [], "target": 10, "active": 0}


def test_casting_state_requires_no_token_for_get(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/casting/state")
    assert r.status_code == 200


def test_casting_state_update_works_without_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/casting/state", json={"paused": True})
    assert r.status_code == 200


def test_casting_state_update_persists_and_returns_state(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/casting/state", headers={"X-Brain-Token": "test-token"},
                    json={"paused": True})
        assert r.status_code == 200
        assert r.json() == {"paused": True, "picked": [], "target": 10}

        r = c.get("/casting/state")
        assert r.json()["paused"] is True


def test_casting_pick_works_without_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
               data={"model": "Alice"}, files={"file": ("face1.jpg", b"x")})
        r = c.post("/casting/pick/Alice")
    assert r.status_code == 200


def test_casting_pick_404_when_model_missing(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/casting/pick/Ghost", headers={"X-Brain-Token": "test-token"})
    assert r.status_code == 404


def test_casting_pick_is_idempotent_and_splits_list(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
               data={"model": "Alice"}, files={"file": ("face1.jpg", b"x")})
        r1 = c.post("/casting/pick/Alice", headers={"X-Brain-Token": "test-token"})
        r2 = c.post("/casting/pick/Alice", headers={"X-Brain-Token": "test-token"})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["picked"] == ["Alice"] == r2.json()["picked"]

        r = c.get("/casting/list")
        assert r.json() == {"models": [], "picked": [{"name": "Alice", "files": ["face1.jpg"]}]}

        r = c.get("/casting/state")
        assert r.json()["picked"] == ["Alice"] and r.json()["active"] == 0


def test_casting_unpick_moves_model_back(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
               data={"model": "Alice"}, files={"file": ("face1.jpg", b"x")})
        c.post("/casting/pick/Alice", headers={"X-Brain-Token": "test-token"})
        r = c.post("/casting/unpick/Alice", headers={"X-Brain-Token": "test-token"})
        assert r.status_code == 200
        assert r.json()["picked"] == []

        r = c.get("/casting/list")
        assert r.json() == {"models": [{"name": "Alice", "files": ["face1.jpg"]}], "picked": []}


def test_casting_delete_model_also_unpicks_it(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
               data={"model": "Alice"}, files={"file": ("face1.jpg", b"x")})
        c.post("/casting/pick/Alice", headers={"X-Brain-Token": "test-token"})
        c.delete("/casting/Alice", headers={"X-Brain-Token": "test-token"})
        r = c.get("/casting/state")
        assert r.json()["picked"] == []


def test_casting_list_excludes_state_file_and_underscore_dirs(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/casting/upload", headers={"X-Brain-Token": "test-token"},
               data={"model": "Alice"}, files={"file": ("face1.jpg", b"x")})
        # trigger _state.json creation
        c.post("/casting/state", headers={"X-Brain-Token": "test-token"}, json={"paused": True})
        # a stray underscore-prefixed directory should never show up as a model
        (data_dir / "casting" / "_scratch").mkdir()
        r = c.get("/casting/list")
        names = [m["name"] for m in r.json()["models"]]
        assert names == ["Alice"]


def test_casting_page_returns_html(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/casting")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="lightbox"' in r.text


def test_startup_fails_without_brain_token(tmp_path, monkeypatch):
    import asyncio
    from brain import config
    from api.main import app, lifespan

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_TOKEN", "change-me")
    config.get_settings.cache_clear()

    async def _enter():
        async with lifespan(app):
            pass

    try:
        with pytest.raises(RuntimeError):
            asyncio.run(_enter())
    finally:
        config.get_settings.cache_clear()


def test_debug_fs_requires_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        r = c.get("/debug/fs")
    assert r.status_code == 401


def test_debug_fs_returns_tree_with_token(data_dir):
    from api.main import app
    # Create some test files to ensure we have entries
    (data_dir / "test_file.txt").write_text("content")
    (data_dir / "subdir").mkdir(exist_ok=True)
    (data_dir / "subdir" / "nested.txt").write_text("nested content")

    with TestClient(app) as c:
        r = c.get("/debug/fs", headers={"X-Brain-Token": "test-token"})
    assert r.status_code == 200
    data = r.json()
    assert "path" in data
    assert data["path"] == str(data_dir)
    assert "entries" in data
    assert len(data["entries"]) > 0
    # Check that entries have required fields
    for entry in data["entries"]:
        assert "name" in entry
        assert "dir" in entry
        # size should only be present for files
        if not entry["dir"]:
            assert "size" in entry
