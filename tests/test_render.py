import json
from brain import render, store

def test_render_page_has_three_levels(data_dir, monkeypatch):
    store.upsert_book("cosmos", "코스모스")
    store.write_md(store.notes_dir("cosmos")/"summary.md", {}, "요약")
    store.write_md(store.notes_dir("cosmos")/"concepts.md", {}, "## 엔트로피\n설명")
    monkeypatch.setattr(render.llm, "complete", lambda s, u, smart=False:
        json.dumps({"초등": "<p>쉬움</p>", "일반": "<p>보통</p>", "전문": "<p>어려움</p>"}))
    out = render.render_book("cosmos", default_level="초등")
    html = out.read_text("utf-8")
    assert "쉬움" in html and "어려움" in html and 'data-default="초등"' in html

def test_shelf_lists_books(data_dir):
    store.upsert_book("cosmos", "코스모스")
    assert "코스모스" in render.render_shelf().read_text("utf-8")
