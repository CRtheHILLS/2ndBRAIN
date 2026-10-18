import json
from pathlib import Path

import pytest

from brain.config import get_settings
from brain import index, retrieve, store


def _patch_sources(monkeypatch):
    from brain import graph, vec
    monkeypatch.setattr(index, "search", lambda q, k: [
        {"slug": "a", "path": "a/raw/x.md", "snippet": "fts-x", "score": -1.0},
        {"slug": "b", "path": "b/raw/y.md", "snippet": "fts-y", "score": -0.5}])
    monkeypatch.setattr(vec, "similar_chunks", lambda q, k=8: [
        {"chunk_id": "c1", "slug": "b", "path": "b/raw/y.md", "start": 0, "text": "vec-y", "distance": 0.1},
        {"chunk_id": "c2", "slug": "a", "path": "a/raw/z.md", "start": 0, "text": "vec-z", "distance": 0.2}])
    monkeypatch.setattr(graph, "search_labels", lambda q, n=3: [{"id": "c:lift"}])
    monkeypatch.setattr(graph, "neighbors", lambda i, d=1, rels=None: {"nodes": [
        {"id": "lesson:a:day-2", "kind": "lesson", "label_ko": "양력 Day 2", "summary": "graph-l"},
        {"id": "c:other", "kind": "concept", "label_ko": "x", "summary": ""}]})


def test_hybrid_rrf_merges_three_sources_and_dedups_paths(data_dir, monkeypatch):
    _patch_sources(monkeypatch)
    out = retrieve.hybrid("양력", k=10)
    paths = [r["path"] for r in out]
    assert len(paths) == len(set(paths)) == 4
    assert paths[0] == "b/raw/y.md"  # fts rank 2 + vec rank 1
    assert out[0]["via"] == ["fts", "vec"]
    assert out[0]["score"] == pytest.approx(1 / 62 + 1 / 61)
    by = {r["path"]: r for r in out}
    assert by["a/days/day-2.json"]["via"] == ["graph"]
    assert by["a/days/day-2.json"]["title"] == "양력 Day 2"
    assert by["a/raw/x.md"]["text"] == "fts-x"
    assert len(retrieve.hybrid("양력", k=2)) == 2


def test_graph_hits_source_path_matches_both_raw_naming_styles(data_dir):
    from brain import catalog, graph
    # upload style: entry file is the original name, raw md is <stem>.md; quest style: file is the .md itself
    for book, fname in (("heli", "My Book.pdf"), ("q1", "src-d01-abcd1234.md")):
        eid = catalog.make_id(book, fname)
        catalog.entry_path(eid).write_text(json.dumps(
            {"id": eid, "book": book, "file": fname, "title": "T"}), "utf-8")
        graph.upsert_node("src:" + eid[:16], "source", "T", summary="요약")
        graph.upsert_node("c:lift", "concept", "양력")
        graph.add_edge("src:" + eid[:16], "c:lift", "about")
        store.write_md(store.raw_dir(book) / (Path(fname).stem + ".md"), {"title": "T"}, "본문")
    hits = retrieve._graph_hits("양력")
    assert {h["path"] for h in hits} == {"heli/raw/My Book.md", "q1/raw/src-d01-abcd1234.md"}
    assert all((get_settings().data_dir / "books" / h["path"]).is_file() for h in hits)


def test_hybrid_slug_filter(data_dir, monkeypatch):
    _patch_sources(monkeypatch)
    out = retrieve.hybrid("양력", k=10, slug="b")
    assert [r["path"] for r in out] == ["b/raw/y.md"]
    assert out[0]["via"] == ["fts", "vec"]


def test_excerpts_filters_slug_and_trims(data_dir):
    filler = "가나다라마바사 " * 100
    store.write_md(store.raw_dir("heli") / "lift.md", {"title": "양력 백과"},
                   filler + "양력은 날개가 공기를 아래로 밀 때 생기는 힘이다. " + filler)
    store.write_md(store.raw_dir("other") / "lift.md", {"title": "다른 책"}, "양력 이야기 " * 20)
    index.rebuild()

    out = retrieve.excerpts("양력", slug="heli", k=3, chars=120)
    assert out and all(e["slug"] == "heli" for e in out)
    e = out[0]
    assert e["title"] == "양력 백과"
    assert e["path"].startswith("heli")
    assert "양력" in e["text"] and len(e["text"]) <= 120

    both = retrieve.excerpts("양력", k=5)
    assert {e["slug"] for e in both} == {"heli", "other"}
    assert len(retrieve.excerpts("양력", k=1)) == 1
