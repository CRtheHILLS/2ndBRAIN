import json
import re

from brain import quest_stages, render, store

D3 = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"


def test_brain_page_renders_with_token_hint_and_d3(data_dir):
    out = render.render_brain_page()
    assert out == store.site_dir() / "brain" / "index.html" and out.exists()
    html = out.read_text("utf-8")
    assert D3 in html
    assert "이 페이지는 토큰이 있어야 데이터를 불러올 수 있어요." in html
    assert "/graph/full" in html and "localStorage" in html and "X-Brain-Token" in html
    m = re.search(r'<script type="application/json" id="areas">(.*?)</script>', html, re.S)
    data = json.loads(m.group(1))
    assert len(data["areas"]) == 17 and len(data["palette"]) == 17
    assert (store.site_dir() / "brain.css").exists()


def test_shelf_links_brain_page(data_dir):
    html = render.render_shelf().read_text("utf-8")
    assert "🧠 두뇌 그래프" in html and "/site/brain/index.html" in html


def test_archive_calls_render_brain_page(monkeypatch):
    calls = []
    monkeypatch.setattr(quest_stages.index, "rebuild", lambda: None)
    monkeypatch.setattr(quest_stages.render, "render_quest", lambda s: calls.append("quest"), raising=False)
    monkeypatch.setattr(quest_stages.render, "render_shelf", lambda: calls.append("shelf"))
    monkeypatch.setattr(quest_stages.render, "render_brain_page", lambda: calls.append("brain"), raising=False)

    def stop(_slug):
        raise RuntimeError("stop")
    monkeypatch.setattr(quest_stages.quest, "load", stop)
    try:
        quest_stages._stage_archive("x")
    except RuntimeError:
        pass
    assert calls == ["quest", "shelf", "brain"]


def test_graph_page_reads_token_from_fragment_and_strips_query(data_dir):
    html = render.render_brain_page().read_text("utf-8")
    assert 'location.hash.replace(/^#/, "")' in html and 'frag.get("t")' in html
    assert 'params.delete("t")' in html  # old ?t= links still work, then vanish from the URL
