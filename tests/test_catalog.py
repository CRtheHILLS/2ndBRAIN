import json

from fastapi.testclient import TestClient

from brain import catalog, ingest, store

TOKEN = {"X-Brain-Token": "test-token"}


def _card(title="양자의 세계", domain="과학", concepts=("양자 얽힘", "중첩")):
    return json.dumps({
        "title": title,
        "summary": "아주 작은 세계의 규칙에 대한 글이야.",
        "domain": domain,
        "tags": ["물리", "양자", "입문"],
        "concepts": list(concepts),
        "entities": ["보어"],
    }, ensure_ascii=False)


def _fake(answer):
    return lambda system, user: answer


# ---------------------------------------------------------------------------
# register / queue
# ---------------------------------------------------------------------------

def test_register_is_idempotent(data_dir):
    p = store.raw_dir("cosmos") / "a.md"
    a = catalog.register("cosmos", "a.txt", p, "sha1")
    b = catalog.register("cosmos", "a.txt", p, "sha1")
    assert a["id"] == b["id"]
    assert a["status"] == "pending" and a["book"] == "cosmos" and a["file"] == "a.txt"
    assert len(catalog.queued()) == 1
    assert catalog.queue_path().read_text("utf-8").strip().count("\n") == 0


def test_register_distinguishes_files_and_books(data_dir):
    p = store.raw_dir("cosmos") / "a.md"
    catalog.register("cosmos", "a.txt", p, "s")
    catalog.register("cosmos", "b.txt", p, "s")
    catalog.register("quantum", "a.txt", p, "s")
    assert len({i["id"] for i in catalog.queued()}) == 3


def test_ingest_auto_registers(data_dir):
    ingest.ingest_file("cosmos", "ch1.txt", "우주는 넓다".encode())
    q = catalog.queued()
    assert [i["file"] for i in q] == ["ch1.txt"]
    assert q[0]["book"] == "cosmos"
    assert q[0]["id"] == catalog.make_id("cosmos", "ch1.txt")
    assert q[0]["path"].endswith("ch1.md")


def test_ingest_failure_in_catalog_does_not_break_ingest(data_dir, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("catalog down")
    monkeypatch.setattr(catalog, "register", boom)
    p = ingest.ingest_file("cosmos", "ch1.txt", "우주".encode())
    assert p.is_file()


# ---------------------------------------------------------------------------
# learning
# ---------------------------------------------------------------------------

def test_learn_one_writes_entry_and_clears_pending(data_dir):
    ingest.ingest_file("cosmos", "ch1.txt", "양자 이야기".encode())
    item = catalog.pending()[0]
    out = catalog.learn_one(item, llm_complete=_fake(_card()))
    assert out is not None
    assert out["status"] == "learned" and out["title"] == "양자의 세계"
    assert out["domain"] == "과학"
    assert out["concepts"] == ["양자 얽힘", "중첩"]
    assert out["entities"] == ["보어"] and out["links"] == []
    assert "learned_at" in out and out["sha256"] == item["sha256"]
    assert catalog.pending() == []
    saved = json.loads(catalog.entry_path(item["id"]).read_text("utf-8"))
    assert saved == out


def test_learn_one_accepts_fenced_json(data_dir):
    ingest.ingest_file("cosmos", "ch1.txt", "양자".encode())
    item = catalog.pending()[0]
    out = catalog.learn_one(item, llm_complete=_fake("여기 있어!\n```json\n" + _card() + "\n```"))
    assert out is not None and out["title"] == "양자의 세계"


def test_learn_one_normalizes_unknown_domain(data_dir):
    ingest.ingest_file("cosmos", "ch1.txt", "양자".encode())
    item = catalog.pending()[0]
    out = catalog.learn_one(item, llm_complete=_fake(_card(domain="우주과학")))
    assert out["domain"] == "기타"


def test_learn_one_failure_keeps_item_pending(data_dir):
    ingest.ingest_file("cosmos", "ch1.txt", "양자".encode())
    item = catalog.pending()[0]
    assert catalog.learn_one(item, llm_complete=_fake("no json here")) is None
    assert [i["id"] for i in catalog.pending()] == [item["id"]]
    assert not catalog.entry_path(item["id"]).exists()


def test_learn_one_swallows_llm_exception(data_dir):
    ingest.ingest_file("cosmos", "ch1.txt", "양자".encode())
    item = catalog.pending()[0]

    def boom(system, user):
        raise RuntimeError("api down")

    assert catalog.learn_one(item, llm_complete=boom) is None
    assert len(catalog.pending()) == 1


def test_learn_one_caps_body_at_15000_chars(data_dir):
    ingest.ingest_file("cosmos", "big.txt", ("가" * 40000).encode())
    item = catalog.pending()[0]
    seen = {}

    def spy(system, user):
        seen["len"] = len(user)
        return _card()

    catalog.learn_one(item, llm_complete=spy)
    assert seen["len"] <= catalog.BODY_LIMIT


def test_learn_one_returns_none_when_source_missing(data_dir):
    item = catalog.register("cosmos", "gone.txt", store.raw_dir("cosmos") / "gone.md", "s")
    assert catalog.learn_one(item, llm_complete=_fake(_card())) is None


def test_learn_pending_respects_limit(data_dir):
    for i in range(3):
        ingest.ingest_file("cosmos", f"c{i}.txt", f"본문 {i}".encode())
    r = catalog.learn_pending(2, llm_complete=_fake(_card()))
    assert r == {"learned": 2, "failed": 0, "remaining": 1}


# ---------------------------------------------------------------------------
# graph & stats
# ---------------------------------------------------------------------------

def test_graph_counts_co_occurrence(data_dir):
    ingest.ingest_file("cosmos", "a.txt", "가".encode())
    ingest.ingest_file("cosmos", "b.txt", "나".encode())
    ingest.ingest_file("quantum", "c.txt", "다".encode())
    pend = catalog.pending()
    answers = {
        "a.txt": _card(concepts=("양자 얽힘", "중첩")),
        "b.txt": _card(concepts=("양자 얽힘", "중첩", "파동함수")),
        "c.txt": _card(domain="철학", concepts=("양자 얽힘", "실재론")),
    }
    for item in pend:
        catalog.learn_one(item, llm_complete=_fake(answers[item["file"]]))

    g = catalog.graph()
    nodes = {n["id"]: n for n in g["nodes"]}
    assert nodes["양자 얽힘"]["count"] == 3
    assert nodes["중첩"]["count"] == 2
    assert nodes["양자 얽힘"]["domains"] == ["과학", "철학"]
    assert nodes["실재론"]["domains"] == ["철학"]

    edges = {(e["a"], e["b"]): e["w"] for e in g["edges"]}
    assert edges[("양자 얽힘", "중첩")] == 2
    assert edges[("중첩", "파동함수")] == 1
    assert edges[("실재론", "양자 얽힘")] == 1
    assert ("실재론", "중첩") not in edges

    on_disk = json.loads(catalog.graph_path().read_text("utf-8"))
    assert on_disk == g


def test_graph_is_empty_without_learned_entries(data_dir):
    assert catalog.graph() == {"nodes": [], "edges": []}


def test_stats_shape(data_dir):
    assert catalog.stats() == {"pending": 0, "learned": 0, "books": 0, "concepts": 0}
    ingest.ingest_file("cosmos", "a.txt", "가".encode())
    ingest.ingest_file("quantum", "b.txt", "나".encode())
    assert catalog.stats() == {"pending": 2, "learned": 0, "books": 2, "concepts": 0}
    catalog.learn_one(catalog.pending()[0], llm_complete=_fake(_card()))
    s = catalog.stats()
    assert s == {"pending": 1, "learned": 1, "books": 2, "concepts": 2}


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------

def test_backfill_registers_preexisting_raw_files(data_dir):
    store.write_md(store.raw_dir("cosmos") / "old.md",
                   {"book": "cosmos", "source": "old.txt", "sha256": "abc", "kind": "text"},
                   "예전에 올린 자료")
    assert catalog.queued() == []
    assert catalog.backfill() == 1
    q = catalog.queued()
    assert [i["file"] for i in q] == ["old.txt"]
    assert q[0]["sha256"] == "abc"
    assert catalog.backfill() == 0


def test_backfill_does_not_duplicate_hook_registrations(data_dir):
    ingest.ingest_file("cosmos", "ch1.txt", "우주".encode())
    assert catalog.backfill() == 0
    assert len(catalog.queued()) == 1


def test_backfill_handles_md_without_frontmatter_source(data_dir):
    p = store.raw_dir("cosmos") / "plain.md"
    p.write_text("프론트매터 없는 파일", "utf-8")
    assert catalog.backfill() == 1
    assert catalog.queued()[0]["file"] == "plain.md"


def test_backfill_skips_learned_entries(data_dir):
    ingest.ingest_file("cosmos", "a.txt", "가".encode())
    catalog.learn_one(catalog.pending()[0], llm_complete=_fake(_card()))
    catalog.queue_path().unlink()
    assert catalog.backfill() == 0


def test_backfill_without_books_dir(data_dir):
    assert catalog.backfill() == 0


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def test_catalog_learn_requires_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        assert c.post("/catalog/learn").status_code == 401


def test_catalog_backfill_requires_token(data_dir):
    from api.main import app
    with TestClient(app) as c:
        assert c.post("/catalog/backfill").status_code == 401


def test_catalog_stats_and_pending_are_open(data_dir):
    from api.main import app
    with TestClient(app) as c:
        c.post("/upload", headers=TOKEN, data={"book": "코스모스"},
               files={"file": ("a.txt", "우주".encode())})
        r = c.get("/catalog/stats")
        assert r.status_code == 200
        assert r.json() == {"pending": 1, "learned": 0, "books": 1, "concepts": 0}

        r = c.get("/catalog/pending")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert set(r.json()[0]) == {"id", "book", "file", "added_at"}
        assert r.json()[0]["file"] == "a.txt"


def test_catalog_learn_endpoint_processes_queue(data_dir, monkeypatch):
    from api.main import app
    monkeypatch.setattr(catalog.llm, "complete", lambda s, u, **kw: _card())
    with TestClient(app) as c:
        for name in ("a.txt", "b.txt"):
            c.post("/upload", headers=TOKEN, data={"book": "코스모스"},
                   files={"file": (name, "우주".encode())})
        r = c.post("/catalog/learn", params={"limit": 1}, headers=TOKEN)
        assert r.status_code == 200
        assert r.json() == {"learned": 1, "failed": 0, "remaining": 1}

        r = c.post("/catalog/learn", headers=TOKEN)
        assert r.json() == {"learned": 1, "failed": 0, "remaining": 0}

        entry_id = catalog.make_id("코스모스", "a.txt")
        r = c.get(f"/catalog/entry/{entry_id}")
        assert r.status_code == 200 and r.json()["title"] == "양자의 세계"

        g = c.get("/catalog/graph").json()
        assert {n["id"] for n in g["nodes"]} == {"양자 얽힘", "중첩"}
        assert g["edges"] == [{"a": "양자 얽힘", "b": "중첩", "w": 2}]


def test_catalog_entry_404_for_unknown_and_bad_id(data_dir):
    from api.main import app
    with TestClient(app) as c:
        assert c.get("/catalog/entry/" + "0" * 64).status_code == 404
        assert c.get("/catalog/entry/nope").status_code == 404
        assert c.get("/catalog/entry/%2e%2e").status_code == 404


def test_catalog_backfill_endpoint(data_dir):
    from api.main import app
    store.write_md(store.raw_dir("코스모스") / "old.md",
                   {"book": "코스모스", "source": "old.txt", "sha256": "abc", "kind": "text"}, "예전 자료")
    with TestClient(app) as c:
        r = c.post("/catalog/backfill", headers=TOKEN)
        assert r.status_code == 200 and r.json() == {"registered": 1}
        assert c.post("/catalog/backfill", headers=TOKEN).json() == {"registered": 0}
        assert [i["file"] for i in c.get("/catalog/pending").json()] == ["old.txt"]
