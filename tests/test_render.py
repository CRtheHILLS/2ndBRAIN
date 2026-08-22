import json
from brain import render, store

FRAGMENTS = {"초등": "<p>쉬움</p>", "일반": "<p>보통</p>", "전문": "<p>어려움</p>"}

def _fake_complete(calls):
    def _complete(system, user, smart=False):
        calls.append(system)
        for level, html in FRAGMENTS.items():
            if level in system:
                return html
        raise AssertionError(f"unexpected system prompt: {system!r}")
    return _complete

def test_render_page_has_three_levels(data_dir, monkeypatch):
    store.upsert_book("cosmos", "코스모스")
    store.write_md(store.notes_dir("cosmos")/"summary.md", {}, "요약")
    store.write_md(store.notes_dir("cosmos")/"concepts.md", {}, "## 엔트로피\n설명")
    calls = []
    monkeypatch.setattr(render.llm, "complete", _fake_complete(calls))
    out = render.render_book("cosmos", default_level="초등")
    html = out.read_text("utf-8")
    assert "쉬움" in html and "어려움" in html and 'data-default="초등"' in html
    assert len(calls) == 3

def test_render_book_persists_and_reuses_cache(data_dir, monkeypatch):
    store.upsert_book("cosmos", "코스모스")
    store.write_md(store.notes_dir("cosmos")/"summary.md", {}, "요약")
    calls = []
    monkeypatch.setattr(render.llm, "complete", _fake_complete(calls))
    render.render_book("cosmos", default_level="일반")
    cache = store.notes_dir("cosmos") / "levels-html.json"
    assert cache.exists()
    cached = json.loads(cache.read_text("utf-8"))
    assert cached == FRAGMENTS
    assert len(calls) == 3

    # re-render with cache: no additional llm calls
    render.render_book("cosmos", default_level="일반", use_cache=True)
    assert len(calls) == 3

def test_shelf_lists_books(data_dir):
    store.upsert_book("cosmos", "코스모스")
    assert "코스모스" in render.render_shelf().read_text("utf-8")
