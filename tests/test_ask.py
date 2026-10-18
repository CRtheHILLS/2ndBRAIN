from fastapi.testclient import TestClient

from brain import ask, graph, think
from brain.connectors.base import Candidate, Doc

H = {"X-Brain-Token": "test-token"}


def _hits(n):
    return [{"text": f"본문 {i}", "slug": "bk", "path": f"bk/notes/{i}.md", "title": f"제목{i}",
             "score": 0.5, "via": "fts"} for i in range(1, n + 1)]


class FakeThink:
    def __init__(self, html="<p>답이에요 [1].</p>"):
        self.html, self.users = html, []

    def __call__(self, kind, system, user, schema=None, **kw):
        assert kind == "ask"
        self.users.append(user)
        return think.ThinkResult({"answer_html": self.html, "citations": [], "used_vault_ratio": 0.1,
                                  "follow_up_quest": ""}, "fake", "m", 1, 1, 0.0)


class FakeRegistry:
    def __init__(self):
        self.searched = 0

    def search_all(self, q, lang, limit_per=5, names=None, timeout=25):
        self.searched += 1
        return [Candidate(url="https://w.org/a", title="웹문서", kind="encyclopedia", authority=0.9,
                          connector="wikipedia")], {}

    def fetch(self, c):
        return Doc(url=c.url, title=c.title, text="웹 본문 " * 10, connector="wikipedia")


def _patch(monkeypatch, n_hits, html="<p>답이에요 [1].</p>"):
    from brain import retrieve
    monkeypatch.setattr(retrieve, "hybrid", lambda q, k=10, slug=None: _hits(n_hits), raising=False)
    ft, reg = FakeThink(html), FakeRegistry()
    monkeypatch.setattr(think, "think", ft)
    monkeypatch.setattr(ask, "registry", reg)
    return ft, reg


def test_ask_vault_only_when_hits_enough(data_dir, monkeypatch):
    graph.upsert_node("c:lift", "concept", "양력")
    _, reg = _patch(monkeypatch, 5)
    r = ask.ask("양력이 뭐야")
    assert r["web_used"] is False and r["used_vault_ratio"] == 1.0 and reg.searched == 0
    assert r["hits"] == 5
    q = graph.by_kind("question")
    assert len(q) == 1 and q[0]["id"].startswith("q:")
    assert any(e["rel"] == "asked" for e in graph.neighbors(q[0]["id"])["edges"])


def test_ask_falls_to_web_when_thin(data_dir, monkeypatch):
    ft, reg = _patch(monkeypatch, 1)
    r = ask.ask("희귀한 질문")
    assert reg.searched == 1 and r["web_used"] is True
    assert r["used_vault_ratio"] == 0.5
    assert "https://w.org/a" in ft.users[0]


def test_ask_citations_are_server_verified(data_dir, monkeypatch):
    _patch(monkeypatch, 3, "<p>둘째 [2] 그리고 지어낸 것 [9].</p>")
    r = ask.ask("질문")
    assert [c["title"] for c in r["citations"]] == ["제목2"]
    assert r["citations"][0]["path"] == "bk/notes/2.md"


def test_ask_503_when_think_unavailable(data_dir, monkeypatch):
    from api.main import app
    from brain import retrieve
    monkeypatch.setattr(retrieve, "hybrid", lambda q, k=10, slug=None: _hits(5), raising=False)

    def boom(*a, **k):
        raise think.ThinkUnavailable(["no key"])
    monkeypatch.setattr(think, "think", boom)
    with TestClient(app) as c:
        assert c.post("/ask", json={"q": "x"}).status_code == 401
        r = c.post("/ask", headers=H, json={"q": "x"})
    assert r.status_code == 503 and "생각" in r.json()["detail"]


def test_ask_answer_html_is_sanitized(data_dir, monkeypatch):
    _patch(monkeypatch, 3, "<script>alert(1)</script><p onclick=x>안녕 [1] [9] <b>굵게</b></p>")
    r = ask.ask("질문")
    h = r["answer_html"]
    assert "script" not in h and "alert" not in h and "onclick" not in h and "<b>" not in h
    assert "[1]" in h and "[9]" not in h and h.startswith("<p>")
