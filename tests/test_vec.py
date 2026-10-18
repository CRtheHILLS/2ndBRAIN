import hashlib
import random

import pytest

from brain import embed, graph, store, vec


def fake_embed(texts):
    out = []
    for t in texts:
        rnd = random.Random(int(hashlib.sha1(t.encode("utf-8")).hexdigest(), 16))
        out.append([rnd.uniform(-1, 1) for _ in range(768)])
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
    monkeypatch.setattr(embed, "embed", lambda texts: None)
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
