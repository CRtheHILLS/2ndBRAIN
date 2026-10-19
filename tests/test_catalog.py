import json

from fastapi.testclient import TestClient

import pytest

from brain import catalog, ingest, store, think

TOKEN = {"X-Brain-Token": "test-token"}


def _card_dict(index=1, title="양자의 세계", domain="과학", concepts=("양자 얽힘", "중첩"),
               field_code="B4"):
    return {
        "index": index,
        "title": title,
        "summary": "아주 작은 세계의 규칙에 대한 글이야.",
        "domain": domain,
        "field_code": field_code,
        "tags": ["물리", "양자", "입문"],
        "concepts": list(concepts),
        "concept_pairs": [{"ko": c, "en": ""} for c in concepts],
        "entities": ["보어"],
    }


def _batch(*cards):
    return json.dumps({"cards": list(cards)}, ensure_ascii=False)


def _card(**kw):
    """Batch answer with a single card for index 1."""
    return _batch(_card_dict(**kw))


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
    assert out["field_code"] == "B4"
    assert out["concept_pairs"] == [{"ko": "양자 얽힘", "en": ""}, {"ko": "중첩", "en": ""}]
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
        seen["user"] = user
        return _card()

    catalog.learn_one(item, llm_complete=spy)
    assert seen["len"] > 0 and seen["user"].count("가") <= catalog.BODY_LIMIT


def test_learn_one_returns_none_when_source_missing(data_dir):
    item = catalog.register("cosmos", "gone.txt", store.raw_dir("cosmos") / "gone.md", "s")
    assert catalog.learn_one(item, llm_complete=_fake(_card())) is None


def test_learn_pending_respects_limit(data_dir):
    for i in range(3):
        ingest.ingest_file("cosmos", f"c{i}.txt", f"본문 {i}".encode())
    r = catalog.learn_pending(2, llm_complete=lambda s, u: _batch(_card_dict(1), _card_dict(2)))
    assert r == {"learned": 2, "failed": 0, "remaining": 1, "new_concepts": ["양자-얽힘", "중첩"]}


def test_learn_batch_matches_by_index_and_marks_missing(data_dir):
    for n in ("a", "b", "c"):
        ingest.ingest_file("cosmos", f"{n}.txt", f"본문 {n}".encode())
    items = catalog.pending()
    answer = _batch(_card_dict(1, title="첫째"), _card_dict(3, title="셋째"))
    out = catalog.learn_batch(items, complete=_fake(answer))
    assert out[0]["title"] == "첫째" and out[1] is None and out[2]["title"] == "셋째"
    assert [i["id"] for i in catalog.pending()] == [items[1]["id"]]


def test_learn_batch_user_message_and_body_budget(data_dir):
    ingest.ingest_file("cosmos", "a.txt", ("가" * 40000).encode())
    ingest.ingest_file("cosmos", "b.txt", ("나" * 40000).encode())
    seen = {}

    def spy(system, user):
        seen["system"], seen["user"] = system, user
        return "no json"

    catalog.learn_batch(catalog.pending(), complete=spy)
    assert "### 자료 1\n제목 힌트: a.txt\n\n" in seen["user"]
    assert "### 자료 2\n제목 힌트: b.txt\n\n" in seen["user"]
    assert seen["user"].count("가") == catalog.BODY_LIMIT // 2
    assert "Z6" in seen["system"] and "B4" in seen["system"]


def test_learn_batch_validates_field_code(data_dir):
    ingest.ingest_file("cosmos", "a.txt", "가".encode())
    ingest.ingest_file("cosmos", "b.txt", "나".encode())
    answer = _batch(_card_dict(1, field_code="QQ9"), _card_dict(2, field_code="B4"))
    out = catalog.learn_batch(catalog.pending(), complete=_fake(answer))
    assert out[0]["field_code"] == "Z6" and out[1]["field_code"] == "B4"


def test_learn_batch_accepts_single_card_object(data_dir):
    ingest.ingest_file("cosmos", "a.txt", "가".encode())
    card = _card_dict()
    del card["index"]
    out = catalog.learn_batch(catalog.pending(), complete=_fake(json.dumps(card, ensure_ascii=False)))
    assert out[0]["title"] == "양자의 세계"


def test_learn_batch_tolerates_missing_optional_fields(data_dir):
    ingest.ingest_file("cosmos", "a.txt", "가".encode())
    answer = _batch({"index": 1, "title": "t", "summary": "s", "domain": "과학"})
    out = catalog.learn_batch(catalog.pending(), complete=_fake(answer))
    assert out[0]["concepts"] == [] and out[0]["field_code"] == "Z6"


def test_learn_pending_filters_by_book(data_dir):
    ingest.ingest_file("cosmos", "a.txt", "가".encode())
    ingest.ingest_file("quantum", "b.txt", "나".encode())
    r = catalog.learn_pending(10, llm_complete=_fake(_card()), book="cosmos")
    assert r["learned"] == 1 and r["remaining"] == 0
    assert [i["book"] for i in catalog.pending()] == ["quantum"]


def test_learn_pending_batches(data_dir):
    for i in range(3):
        ingest.ingest_file("cosmos", f"c{i}.txt", f"본문 {i}".encode())
    calls = []

    def fake(system, user):
        calls.append(user)
        n = user.count("### 자료 ")
        return _batch(*[_card_dict(k + 1) for k in range(n)])

    r = catalog.learn_pending(10, llm_complete=fake, batch_size=2)
    assert len(calls) == 2 and r["learned"] == 3


def test_learn_pending_uses_think_when_no_fake(data_dir, monkeypatch):
    ingest.ingest_file("cosmos", "a.txt", "가".encode())
    calls = []

    def fake(system, user, smart):
        calls.append(smart)
        return _card(), "fake", "m", 1, 1

    monkeypatch.setattr(think, "complete_text", fake)
    assert catalog.learn_pending(5)["learned"] == 1
    assert calls == [False]


def test_learn_pending_propagates_think_unavailable(data_dir, monkeypatch):
    ingest.ingest_file("cosmos", "a.txt", "가".encode())

    def boom(system, user, smart):
        raise think.ThinkUnavailable(["no key"])

    monkeypatch.setattr(think, "complete_text", boom)
    with pytest.raises(think.ThinkUnavailable):
        catalog.learn_pending(5)
    assert len(catalog.pending()) == 1


def test_catalog_learn_endpoint_503_when_think_unavailable(data_dir, monkeypatch):
    from api.main import app

    def boom(system, user, smart):
        raise think.ThinkUnavailable(["no key"])

    monkeypatch.setattr(think, "complete_text", boom)
    with TestClient(app) as c:
        c.post("/upload", headers=TOKEN, data={"book": "코스모스"},
               files={"file": ("a.txt", "우주".encode())})
        r = c.post("/catalog/learn", headers=TOKEN)
        assert r.status_code == 503
        assert "생각 담당(모델)을 지금 쓸 수 없어요" in r.json()["detail"]
        assert "no key" in r.json()["detail"]


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
    monkeypatch.setattr(think, "complete_text",
                        lambda s, u, smart: (_card(), "fake", "m", 1, 1))
    with TestClient(app) as c:
        for name in ("a.txt", "b.txt"):
            c.post("/upload", headers=TOKEN, data={"book": "코스모스"},
                   files={"file": (name, "우주".encode())})
        r = c.post("/catalog/learn", params={"limit": 1}, headers=TOKEN)
        assert r.status_code == 200
        assert r.json() == {"learned": 1, "failed": 0, "remaining": 1, "new_concepts": ["양자-얽힘", "중첩"]}

        r = c.post("/catalog/learn", headers=TOKEN)
        assert r.json() == {"learned": 1, "failed": 0, "remaining": 0, "new_concepts": []}

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


def test_after_learn_triggers_rebridge(data_dir, monkeypatch):
    from brain import bridge
    calls = {}

    def rebridge(ids, **kw):
        calls["rebridge"] = list(ids)
        return [{"src": ids[0], "dst": "angular-momentum", "rel": "bridge", "reason": "이유"}]
    monkeypatch.setattr(bridge, "rebridge", rebridge)
    monkeypatch.setattr(bridge, "rerender_affected", lambda ids: calls.setdefault("rerender", list(ids)))
    entry = {"id": "ab" * 32, "book": "헬리콥터", "title": "자이로", "field_code": "B2",
             "concept_pairs": [{"ko": "자이로스코프", "en": "Gyroscope"}]}
    assert catalog._after_learn([entry]) == ["gyroscope"]
    assert calls["rebridge"] == ["gyroscope"]
    assert set(calls["rerender"]) == {"gyroscope", "angular-momentum"}

    def broken(ids, **kw):
        raise think.ThinkUnavailable(["no key"])
    monkeypatch.setattr(bridge, "rebridge", broken)
    entry2 = {**entry, "id": "cd" * 32, "concept_pairs": [{"ko": "로터", "en": "Rotor"}]}
    assert catalog._after_learn([entry2]) == ["rotor"]  # never breaks /catalog/learn


def test_after_learn_leaves_quest_books_to_the_bridge_stage(data_dir, monkeypatch):
    from brain import bridge, quest
    quest.save("quest-heli", {"slug": "quest-heli", "plan": {"title_ko": "헬리콥터"}})
    seen = []
    monkeypatch.setattr(bridge, "rebridge", lambda ids, **kw: seen.append(list(ids)) or [])
    entry = {"id": "ef" * 32, "book": "quest-heli", "title": "자이로", "field_code": "B2",
             "concept_pairs": [{"ko": "자이로스코프", "en": "Gyroscope"}]}
    assert catalog._after_learn([entry]) == ["gyroscope"]
    assert seen == []


def test_catalog_card_summary_and_domain_have_defaults():
    from brain import models
    c = models.CatalogCard(index=1, title="제목")
    assert c.summary == "" and c.domain == "기타"
