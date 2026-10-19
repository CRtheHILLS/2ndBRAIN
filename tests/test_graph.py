import json

import pytest

from brain import catalog, graph, ingest


def _events(data_dir):
    p = data_dir / "graph" / "events.jsonl"
    return [json.loads(x) for x in p.read_text("utf-8").splitlines()]


def test_upsert_node_writes_event_and_row_and_aliases(data_dir):
    n = graph.upsert_node("quantum-entanglement", "concept", "양자 얽힘", "Quantum entanglement",
                          wikidata="Q215675", field_code="B4")
    assert _events(data_dir)[0]["op"] == "node"
    assert "양자 얽힘" in (data_dir / "graph" / "events.jsonl").read_text("utf-8")
    assert n["label_ko"] == "양자 얽힘" and graph.get_node("quantum-entanglement")["field_code"] == "B4"
    assert graph.find_alias("양자  얽힘") == "quantum-entanglement"
    assert graph.find_alias("QUANTUM entanglement") == "quantum-entanglement"
    assert graph.find_alias("wd:Q215675") == "quantum-entanglement"


def test_upsert_does_not_blank_existing_fields(data_dir):
    graph.upsert_node("a", "concept", "에이", "A", field_code="B4", summary="s")
    n = graph.upsert_node("a", "concept", "", "", summary="")
    assert (n["label_ko"], n["label_en"], n["field_code"], n["summary"]) == ("에이", "A", "B4", "s")


def test_related_weight_accumulates_other_rels_overwrite(data_dir):
    for i in "ab":
        graph.upsert_node(i, "concept", i)
    graph.add_edge("a", "b", "related", 1.0)
    graph.add_edge("a", "b", "related", 2.0)
    graph.add_edge("a", "b", "requires", 1.0)
    graph.add_edge("a", "b", "requires", 5.0)
    w = {e["rel"]: e["weight"] for e in graph.neighbors("a")["edges"]}
    assert w == {"related": 3.0, "requires": 5.0}


def test_invalid_rel_raises(data_dir):
    with pytest.raises(ValueError):
        graph.add_edge("a", "b", "friends_with")


def test_redirect_resolves_in_get_and_neighbors(data_dir):
    graph.upsert_node("new", "concept", "새것")
    graph.upsert_node("x", "concept", "엑스")
    graph.add_edge("new", "x", "related")
    graph.redirect("old", "new")
    assert graph.resolve("old") == "new"
    assert graph.get_node("old")["id"] == "new"
    nb = graph.neighbors("old")
    assert nb["center"] == "new" and {n["id"] for n in nb["nodes"]} == {"new", "x"}


def _chain():
    for i in "abcd":
        graph.upsert_node(i, "concept", i)
    graph.add_edge("a", "b", "related")
    graph.add_edge("b", "c", "related")
    graph.add_edge("c", "d", "related")


def test_neighbors_depth2(data_dir):
    _chain()
    assert {n["id"] for n in graph.neighbors("a", 1)["nodes"]} == {"a", "b"}
    d2 = graph.neighbors("a", 2)
    assert {n["id"] for n in d2["nodes"]} == {"a", "b", "c"} and len(d2["edges"]) == 2
    assert {n["id"] for n in graph.neighbors("a", 9)["nodes"]} == {"a", "b", "c", "d"}
    assert len(graph.neighbors("a", 3, rels=["requires"])["edges"]) == 0


def test_search_labels_and_full(data_dir):
    _chain()
    graph.upsert_node("qb", "concept", "큐비트", "Qubit")
    assert [n["id"] for n in graph.search_labels("QUBIT")] == ["qb"]
    f = graph.full(2)
    assert f["truncated"] is True and len(f["nodes"]) == 2
    assert all(e["src"] in {n["id"] for n in f["nodes"]} for e in f["edges"])
    assert {n["id"] for n in graph.full()["nodes"]} == {"a", "b", "c", "d", "qb"}


def test_rebuild_from_events_is_identical(data_dir):
    graph.upsert_node("a", "concept", "에이", "A", field_code="B4", tags=["t"])
    graph.upsert_node("b", "concept", "비", field_code="B4")
    graph.upsert_node("c", "concept", "씨")
    graph.add_edge("a", "b", "related", 1.0)
    graph.add_edge("a", "b", "related", 1.0)
    graph.add_edge("b", "c", "requires")
    graph.add_edge("a", "c", "bridge")
    graph.redirect("z", "c")
    before = (graph.stats(), graph.neighbors("a", 2), graph.find_alias("에이"))
    n = graph.rebuild()
    assert n == len(_events(data_dir))
    assert (graph.stats(), graph.neighbors("a", 2), graph.find_alias("에이")) == before
    assert graph.resolve("z") == "c"


def _entry(**kw):
    e = {"id": "ab" * 32, "book": "cosmos", "file": "f.txt", "title": "양자의 세계",
         "summary": "요약", "field_code": "B4", "tags": ["물리"],
         "concepts": ["양자 얽힘", "중첩"],
         "concept_pairs": [{"ko": "양자 얽힘", "en": "Quantum entanglement"},
                           {"ko": "중첩", "en": ""}]}
    return {**e, **kw}


def test_ingest_card_links_source_book_concepts(data_dir):
    new = graph.ingest_card(_entry())
    assert new == ["quantum-entanglement", "중첩"]
    nb = graph.neighbors("src:" + "ab" * 8)
    assert sorted(e["rel"] for e in nb["edges"]) == ["about", "about", "in_book"]
    assert graph.get_node("book:cosmos")["kind"] == "book"
    rel = graph.neighbors("quantum-entanglement", rels=["related"])["edges"]
    assert len(rel) == 1 and rel[0]["weight"] == 1.0
    assert graph.node_ids_in_book("cosmos", kind="source") == ["src:" + "ab" * 8]
    assert graph.ingest_card(_entry(id="cd" * 32)) == []
    assert graph.neighbors("중첩", rels=["related"])["edges"][0]["weight"] == 2.0


def test_ingest_card_invalid_field_code_falls_back(data_dir):
    graph.ingest_card(_entry(field_code="??"))
    assert graph.get_node("중첩")["field_code"] == "Z6"


def test_catalog_learn_creates_concepts_in_graph(data_dir):
    ingest.ingest_file("cosmos", "a.txt", "본문".encode())
    card = {"index": 1, "title": "t", "summary": "s", "domain": "과학", "field_code": "B4",
            "tags": [], "concepts": ["양자 얽힘", "중첩"],
            "concept_pairs": [{"ko": "양자 얽힘", "en": ""}, {"ko": "중첩", "en": ""}],
            "entities": []}
    r = catalog.learn_pending(5, llm_complete=lambda s, u: json.dumps({"cards": [card]}, ensure_ascii=False))
    assert len(r["new_concepts"]) == 2 and graph.stats()["concepts"] == 2


def test_graph_api(data_dir):
    from fastapi.testclient import TestClient
    from api.main import app
    c = TestClient(app)
    h = {"X-Brain-Token": "test-token"}
    graph.ingest_card(_entry())
    assert c.get("/graph/stats").status_code == 401
    assert c.get("/graph/stats", headers=h).json()["concepts"] == 2
    assert c.get("/graph?center=중첩").status_code in (401, 403)
    assert c.get("/graph", headers=h).status_code == 400
    assert c.get("/graph?center=중첩", headers=h).json()["center"] == "중첩"
    assert len(c.get("/graph?kind=concept", headers=h).json()["nodes"]) == 2
    assert len(c.get("/graph?field=B4", headers=h).json()["nodes"]) >= 2
    assert len(c.get("/graph/full", headers=h).json()["nodes"]) == 4
    assert c.post("/graph/rebuild", headers=h).json()["replayed"] > 0


def test_edge_written_before_redirect_is_reachable(data_dir):
    for i in ("x", "old", "new"):
        graph.upsert_node(i, "concept", i)
    graph.add_edge("x", "old", "related")
    graph.redirect("old", "new")
    nb = graph.neighbors("new")
    assert {n["id"] for n in nb["nodes"]} == {"new", "x"}
    assert [(e["src"], e["dst"]) for e in nb["edges"]] == [("x", "new")]
    assert graph.get_node("old")["id"] == "new"
    graph.upsert_node("old", "concept", "다시")
    assert graph.get_node("new")["label_ko"] == "다시"
    graph.add_edge("old", "x", "requires")
    assert {(e["src"], e["dst"]) for e in graph.neighbors("new", rels=["requires"])["edges"]} == {("new", "x")}


def test_node_ids_in_book_includes_concepts_and_filters_kind(data_dir):
    graph.ingest_card(_entry())
    graph.ingest_card(_entry(id="ef" * 32, book="other", concepts=["다른"],
                             concept_pairs=[{"ko": "다른", "en": ""}]))
    src = "src:" + "ab" * 8
    assert graph.node_ids_in_book("cosmos") == sorted([src, "quantum-entanglement", "중첩"])
    assert graph.node_ids_in_book("cosmos", kind="concept") == ["quantum-entanglement", "중첩"]
    assert graph.node_ids_in_book("cosmos", kind="source") == [src]


def test_book_title_cannot_steal_concept_alias(data_dir):
    graph.upsert_node("cosmos-concept", "concept", "코스모스")
    graph.upsert_node("book:코스모스", "book", "코스모스")
    graph.upsert_node("src:1", "source", "코스모스")
    graph.add_alias("코스모스", "src:1")
    assert graph.find_alias("코스모스") == "cosmos-concept"


def test_fallback_field_code_never_overwrites_real(data_dir):
    graph.upsert_node("a", "concept", "a", field_code="B4")
    assert graph.upsert_node("a", "concept", "a", field_code="Z6")["field_code"] == "B4"
    graph.upsert_node("b", "concept", "b", field_code="Z6")
    assert graph.upsert_node("b", "concept", "b", field_code="B4")["field_code"] == "B4"


def test_rebuild_skips_torn_log_lines(data_dir, caplog):
    graph.upsert_node("c:a", "concept", "가")
    with graph._log_path().open("a", encoding="utf-8") as f:
        f.write('{"op": "upsert_node", "id": "c:b"\n')  # torn line (crash mid-write)
    graph.upsert_node("c:c", "concept", "다")
    with caplog.at_level("WARNING"):
        graph.rebuild()
    assert graph.get_node("c:a") and graph.get_node("c:c")
    assert any("not JSON" in r.message for r in caplog.records)


def test_db_schema_runs_once_per_path(data_dir, monkeypatch):
    from brain import db, vec
    db.connect().close()
    calls = []
    monkeypatch.setattr(vec, "ensure_tables", lambda con: calls.append(1) or True)
    for _ in range(3):
        db.connect().close()
    assert calls == []


def test_remove_node_tombstone_and_rebuild(data_dir):
    graph.upsert_node("a", "concept", "에이")
    graph.upsert_node("b", "concept", "비")
    graph.upsert_node("c", "concept", "씨")
    graph.add_edge("a", "b", "related")
    graph.add_edge("c", "a", "related")
    graph.add_alias("에이별칭", "a")
    before_events = len(_events(data_dir))
    assert graph.remove_node("a") is True
    assert len(_events(data_dir)) == before_events + 1 and _events(data_dir)[-1]["op"] == "remove"
    assert graph.get_node("a") is None and graph.find_alias("에이별칭") is None
    assert graph.neighbors("b")["edges"] == [] and graph.neighbors("c")["edges"] == []
    stats_before = graph.stats()
    graph.rebuild()
    assert graph.get_node("a") is None and graph.find_alias("에이별칭") is None
    assert graph.stats() == stats_before


def test_remove_node_missing_returns_false(data_dir):
    assert graph.remove_node("ghost") is False
