import hashlib
import math
import random

import pytest

from brain import embed, graph, store, vec


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def fake_embed(texts, task="document"):
    out = []
    for t in texts:
        rnd = random.Random(int(hashlib.sha1(t.encode("utf-8")).hexdigest(), 16))
        out.append(_unit([rnd.uniform(-1, 1) for _ in range(768)]))
    return out


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(embed, "embed", fake_embed)


def _need_vec(data_dir):
    from brain import db
    db.connect().close()
    if not vec.AVAILABLE:
        pytest.skip("sqlite-vec not loadable here")


def test_index_and_similar_nodes_roundtrip(data_dir, fake):
    _need_vec(data_dir)
    graph.upsert_node("c:lift", "concept", "양력", "lift", summary="날개가 공기를 밀어 생기는 힘")
    graph.upsert_node("c:jazz", "concept", "재즈", "jazz", summary="즉흥 연주 음악")
    assert vec.index_nodes(["c:lift", "c:jazz"]) == 2
    hits = vec.similar_nodes(text="양력 lift 날개가 공기를 밀어 생기는 힘", k=2)
    assert hits[0][0] == "c:lift"
    by_id = vec.similar_nodes(node_id="c:lift", k=2)
    assert [i for i, _ in by_id] == ["c:jazz"]


def test_no_embedding_provider_is_silent(data_dir, monkeypatch):
    monkeypatch.setattr(embed, "embed", lambda texts, task="document": None)
    graph.upsert_node("c:lift", "concept", "양력", "lift")
    assert vec.index_nodes(["c:lift"]) == 0
    assert vec.index_doc("b", "b/raw/x.md", "가" * 2000) == 0
    assert vec.similar_nodes(text="양력") == []
    assert vec.similar_nodes(node_id="c:lift") == []
    assert vec.similar_chunks("양력") == []


def test_embed_without_key_returns_none(data_dir):
    assert embed.embed(["a"]) is None


def test_unavailable_path_returns_empty(data_dir, fake, monkeypatch):
    monkeypatch.setattr(vec, "ensure_tables", lambda con: False)
    monkeypatch.setattr(vec, "AVAILABLE", False)
    graph.upsert_node("c:lift", "concept", "양력")
    assert vec.index_nodes(["c:lift"]) == 0
    assert vec.similar_chunks("양력") == []
    assert vec.index_book("b") == 0


def test_index_book_chunks_and_skips_existing(data_dir, fake):
    _need_vec(data_dir)
    store.write_md(store.raw_dir("heli") / "a.md", {"title": "A"}, "가" * 1700)
    assert vec.index_book("heli") == 3  # 800 + 800 + 100
    assert vec.index_book("heli") == 0
    got = vec.similar_chunks("가" * 800, k=3)
    assert {c["start"] for c in got} == {0, 800, 1600}
    assert all(c["slug"] == "heli" and c["path"] == "heli/raw/a.md" for c in got)


def _axis(*vals):
    return _unit(list(vals) + [0.0] * (768 - len(vals)))


def test_knn_orders_by_distance(data_dir, monkeypatch):
    _need_vec(data_dir)
    vectors = {"near": _axis(0.9, 0.1), "exact": _axis(1, 0), "far": _axis(0, 1)}
    monkeypatch.setattr(embed, "embed", lambda texts, task="document": [vectors[t] for t in texts])
    for nid in vectors:
        graph.upsert_node(f"c:{nid}", "concept", nid)  # node text is just the label
    assert vec.index_nodes([f"c:{n}" for n in vectors]) == 3
    from contextlib import closing
    from brain import db
    with closing(db.connect()) as con:
        rows = vec._knn(con, "node_vec", "node_id", _axis(1, 0), 3)
    assert [r[0] for r in rows] == ["c:exact", "c:near", "c:far"]
    dists = [r[1] for r in rows]
    assert dists == sorted(dists) and dists[0] < 1e-6 < dists[-1]


def test_index_doc_reembeds_edited_chunk_and_delete_book(data_dir, fake):
    _need_vec(data_dir)
    assert vec.index_doc("b", "b/raw/x.md", "가" * 800 + "나" * 100) == 2
    assert vec.index_doc("b", "b/raw/x.md", "가" * 800 + "나" * 100) == 0
    assert vec.index_doc("b", "b/raw/x.md", "가" * 800 + "다" * 100) == 1  # only the edited tail
    assert vec.index_doc("keep", "keep/raw/y.md", "라" * 100) == 1
    assert vec.delete_book("b") == 2
    assert [c["slug"] for c in vec.similar_chunks("라" * 100, k=5)] == ["keep"]
    assert vec.delete_book("b") == 0


def test_embed_normalizes_and_sets_task_type(data_dir, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from brain import config
    config.get_settings.cache_clear()
    sent = []

    class R:
        def raise_for_status(self): pass
        def json(self): return {"embeddings": [{"values": [3.0, 4.0] + [0.0] * 766}]}

    def post(url, headers, json, timeout):
        sent.append(json)
        return R()

    monkeypatch.setattr(embed.httpx, "post", post)
    out = embed.embed(["질문"], task="query")
    assert out[0][:2] == pytest.approx([0.6, 0.8])
    assert sent[0]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    embed.embed(["문서"])
    assert sent[1]["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    config.get_settings.cache_clear()
