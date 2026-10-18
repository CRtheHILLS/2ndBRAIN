import httpx
import respx

from brain.connectors import arxiv, base, openalex, pubmed, registry, semanticscholar, wikipedia


def test_normalize_url_merges_variants():
    a = base.normalize_url("http://m.wikipedia.org/wiki/X?utm_source=t#a")
    b = base.normalize_url("https://wikipedia.org/wiki/X/")
    assert a == b == "https://wikipedia.org/wiki/X"


def test_normalize_url_keeps_other_query_and_strips_www():
    assert base.normalize_url("HTTPS://WWW.Example.com/a?id=1&fbclid=z") == "https://example.com/a?id=1"


@respx.mock
def test_wikipedia_search_and_fetch():
    respx.get("https://ko.wikipedia.org/w/api.php").mock(side_effect=[
        httpx.Response(200, json={"query": {"search": [{"title": "양자역학", "snippet": "<b>양자</b> 이론"}]}}),
        httpx.Response(200, json={"query": {"pages": {"1": {
            "title": "양자역학", "extract": "양자역학은 물리학이다.",
            "links": [{"title": "물리학"}, {"title": "입자"}]}}}}),
    ])
    c = wikipedia.WikipediaConnector()
    cands = c.search("양자역학", "ko", 3)
    assert cands[0].title == "양자역학" and cands[0].kind == "encyclopedia"
    assert cands[0].connector == "wikipedia" and cands[0].authority == 0.9
    assert cands[0].url == "https://ko.wikipedia.org/wiki/%EC%96%91%EC%9E%90%EC%97%AD%ED%95%99"
    assert cands[0].snippet == "양자 이론"
    doc = c.fetch(cands[0])
    assert len(doc.text) > 0 and doc.meta["links"] == ["물리학", "입자"]


@respx.mock
def test_openalex_search_and_fetch():
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json={"results": [{
        "id": "https://openalex.org/W1", "title": "Quantum", "publication_year": 2020,
        "cited_by_count": 99, "doi": "https://doi.org/10.1/x",
        "primary_location": {"landing_page_url": "https://example.org/p"},
        "open_access": {"oa_url": "https://example.org/p.pdf"},
        "abstract_inverted_index": {"Hello": [0], "world": [1]}}]}))
    c = openalex.OpenAlexConnector()
    x = c.search("quantum", "en", 3)[0]
    assert x.title == "Quantum" and x.kind == "paper" and x.connector == "openalex"
    assert x.year == 2020 and x.url == "https://example.org/p"
    assert x.extra == {"cited_by": 99, "oa_pdf": "https://example.org/p.pdf", "doi": "https://doi.org/10.1/x"}
    assert 0.89 < x.authority < 0.91
    assert len(c.fetch(x).text) > 0


def test_openalex_abstract_from_inverted_index():
    idx = {"world": [1, 3], "Hello": [0], "again": [2]}
    assert openalex.abstract_from_inverted_index(idx) == "Hello world again world"
    assert openalex.abstract_from_inverted_index(None) == ""


ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/1234.5678v1</id><title>Quantum  Things</title>
<summary>An abstract here.</summary><published>2021-03-04T00:00:00Z</published></entry></feed>"""


@respx.mock
def test_arxiv_search_and_fetch():
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=ATOM))
    c = arxiv.ArxivConnector()
    x = c.search("quantum", "en", 3)[0]
    assert x.title == "Quantum Things" and x.kind == "paper" and x.connector == "arxiv" and x.year == 2021
    assert c.fetch(x).text == "An abstract here."


EFETCH = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
<Journal><JournalIssue><PubDate><Year>2019</Year></PubDate></JournalIssue></Journal>
<ArticleTitle>Brain study</ArticleTitle>
<Abstract><AbstractText>Part one.</AbstractText><AbstractText>Part two.</AbstractText></Abstract>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>7</PMID><Article>
<ArticleTitle>Other study</ArticleTitle><Abstract><AbstractText>Other.</AbstractText></Abstract>
</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""


@respx.mock
def test_pubmed_search_and_fetch():
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["7", "99", "42"]}}))
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi").mock(
        return_value=httpx.Response(200, text=EFETCH))
    c = pubmed.PubMedConnector()
    cands = c.search("brain", "en", 3)
    assert len(cands) == 2  # id 99 was omitted by efetch
    by_title = {y.title: y for y in cands}
    assert by_title["Other study"].url == "https://pubmed.ncbi.nlm.nih.gov/7"
    x = by_title["Brain study"]
    assert x.kind == "paper" and x.connector == "pubmed" and x.year == 2019
    assert x.url == "https://pubmed.ncbi.nlm.nih.gov/42" and x.extra["pmid"] == "42"
    assert "Part one." in c.fetch(x).text


@respx.mock
def test_semanticscholar_search_and_fetch():
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json={"data": [{
            "title": "S2 paper", "year": 2018, "citationCount": 10, "url": "https://s2/p",
            "abstract": "Abstract text", "openAccessPdf": {"url": "https://s2/p.pdf"}}]}))
    c = semanticscholar.SemanticScholarConnector()
    x = c.search("q", "en", 3)[0]
    assert x.title == "S2 paper" and x.kind == "paper" and x.connector == "semanticscholar"
    assert len(c.fetch(x).text) > 0


@respx.mock
def test_semanticscholar_429_is_error_status():
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(return_value=httpx.Response(429))
    cands, status = registry.search_all("q", "en", names=["semanticscholar"])
    assert cands == [] and status["semanticscholar"] == "error:429"


def test_search_all_collects_partial_results_when_one_connector_fails(monkeypatch):
    class Good:
        name = "good"

        def search(self, query, lang, limit):
            return [base.Candidate(url="https://a", title="A", kind="web", connector="good")]

    class Bad:
        name = "bad"

        def search(self, query, lang, limit):
            raise RuntimeError("boom")

    monkeypatch.setattr(registry, "all_connectors", lambda: {"good": Good(), "bad": Bad()})
    cands, status = registry.search_all("q", "ko")
    assert [c.title for c in cands] == ["A"]
    assert status["good"] == "ok:1" and status["bad"].startswith("error:")


def test_search_all_timeout_is_shared_deadline(monkeypatch):
    import time

    class Slow:
        def search(self, query, lang, limit):
            time.sleep(0.3)
            return []

    class Fast:
        def search(self, query, lang, limit):
            return [base.Candidate(url="https://a", title="A", kind="web", connector="fast")]

    monkeypatch.setattr(registry, "all_connectors",
                        lambda: {"slow1": Slow(), "slow2": Slow(), "slow3": Slow(), "fast": Fast()})
    t0 = time.monotonic()
    cands, status = registry.search_all("q", "ko", timeout=0.1)
    assert time.monotonic() - t0 < 0.25
    assert status["slow1"] == status["slow2"] == status["slow3"] == "error:timeout"
    assert status["fast"] == "ok:1" and len(cands) == 1


def test_all_connectors_names():
    assert set(registry.all_connectors()) == {"wikipedia", "openalex", "arxiv", "pubmed", "semanticscholar",
                                              "webpage", "youtube", "ddgs", "xai", "vault"}


# ---- Task 9: webpage / youtube / ddgs / xai / vault ----
import pymupdf  # noqa: E402

from brain.connectors import ddgs_web, vault, webpage, xai_search, youtube  # noqa: E402
from brain.connectors.base import Candidate, Doc  # noqa: E402


def test_extract_html_uses_trafilatura_on_local_string():
    html = ("<html><head><title>양자 문서</title></head><body><article><h1>양자</h1>"
            + "<p>양자역학은 원자 규모의 물리 현상을 설명하는 이론이다. 많은 실험이 이를 뒷받침한다.</p>" * 5
            + "</article></body></html>")
    title, text = webpage.extract_html(html, "https://example.org/q")
    assert "양자" in title
    assert "양자역학" in text


def test_extract_pdf_caps_pages():
    doc = pymupdf.open()
    for i in (1, 2, 3):
        doc.new_page().insert_text((72, 72), f"content {i}")
    data = doc.tobytes()
    text = webpage.extract_pdf(data, max_pages=2)
    assert "<!-- page 1 -->" in text and "<!-- page 2 -->" in text
    assert "<!-- page 3 -->" not in text and "content 3" not in text


def test_ddgs_kind_guess_and_empty_on_exception(monkeypatch):
    class Fake:
        def text(self, query, max_results, region):
            assert region == "kr-kr"
            return [
                {"title": "a", "href": "https://www.youtube.com/watch?v=abc", "body": "x"},
                {"title": "b", "href": "https://www.nasa.gov/x", "body": "y"},
                {"title": "c", "href": "https://foo.tistory.com/1", "body": "z"},
                {"title": "d", "href": "https://example.com/", "body": "w"},
            ]
    monkeypatch.setattr(ddgs_web, "DDGS", Fake)
    cands = ddgs_web.search("q", "ko", 4)
    assert [c.kind for c in cands] == ["video", "official", "forum", "web"]
    assert all(c.connector == "ddgs" for c in cands)

    class Boom:
        def text(self, *a, **k):
            raise RuntimeError("rate limit")
    monkeypatch.setattr(ddgs_web, "DDGS", Boom)
    assert ddgs_web.search("q", "en", 3) == []


def _set_xai_key(monkeypatch, value):
    from brain import config
    monkeypatch.setenv("XAI_API_KEY", value)
    config.get_settings.cache_clear()


def test_xai_search_returns_empty_without_key(data_dir, monkeypatch):
    _set_xai_key(monkeypatch, "")
    with respx.mock:  # any request would raise
        assert xai_search.search("q", "ko", 3) == []


@respx.mock
def test_xai_search_parses_json(data_dir, monkeypatch):
    _set_xai_key(monkeypatch, "k")
    text = 'Here: [{"url": "https://mit.edu/a", "title": "A", "kind": "web"}, {"url": "https://x.com/b", "title": "B"}] done'
    route = respx.post("https://api.x.ai/v1/responses").mock(return_value=httpx.Response(200, json={
        "output": [{"type": "web_search_call"},
                   {"type": "message", "content": [{"type": "output_text", "text": text}]}]}))
    cands = xai_search.search("q", "ko", 2)
    assert route.called
    assert [c.url for c in cands] == ["https://mit.edu/a", "https://x.com/b"]
    assert cands[0].kind == "official" and cands[0].connector == "xai"


def test_vault_search_wraps_index_hits(data_dir):
    d = data_dir / "books" / "qm" / "notes"
    d.mkdir(parents=True)
    (d / "intro.md").write_text("---\ntitle: t\n---\n양자역학 파동함수 설명 본문입니다.\n", encoding="utf-8")
    from brain import index
    index.rebuild()
    cands = vault.search("양자역학", "ko", 3)
    assert cands
    c = cands[0]
    assert c.url.startswith("vault://qm/") and c.kind == "textbook" and c.authority == 0.95
    assert c.connector == "vault"
    assert "파동함수" in vault.fetch(c).text


def test_registry_fetch_routes_youtube_vault_and_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(youtube, "fetch", lambda c: calls.append("yt") or Doc(url=c.url, title="v", text="t"))
    monkeypatch.setattr(vault, "fetch", lambda c: calls.append("vault") or Doc(url=c.url, title="n", text="t"))
    monkeypatch.setattr(webpage, "fetch_url",
                        lambda url, max_pages=None: calls.append("web") or Doc(url=url, title="w", text="t"))
    monkeypatch.setattr(wikipedia, "fetch_title", lambda t, lang: None)

    def mk(url, conn):
        return Candidate(url=url, title="x", kind="web", connector=conn)
    registry.fetch(mk("https://youtu.be/abc", "ddgs"))
    registry.fetch(mk("vault://qm/notes/a.md", "vault"))
    registry.fetch(mk("https://en.wikipedia.org/wiki/X", "wikipedia"))
    registry.fetch(mk("https://example.com/p", "webpage"))
    assert calls == ["yt", "vault", "web", "web"]
    assert {"webpage", "youtube", "ddgs", "xai", "vault"} <= set(registry.all_connectors())


@respx.mock
def test_download_stops_at_max_bytes_and_rejects_big_content_length():
    def chunks():
        for _ in range(100):
            yield b"x" * 100
    respx.get("https://example.com/big").mock(return_value=httpx.Response(200, content=chunks()))
    data, _ = webpage.download("https://example.com/big", max_bytes=500)
    assert len(data) == 500
    respx.get("https://example.com/huge").mock(return_value=httpx.Response(
        200, content=b"abc", headers={"content-length": "999999"}))
    import pytest
    with pytest.raises(ValueError):
        webpage.download("https://example.com/huge", max_bytes=500)


def test_registry_fetch_never_raises_and_falls_back(monkeypatch):
    class Boom:
        name = "boom"
        def fetch(self, c):
            raise RuntimeError("x")
    monkeypatch.setattr(registry, "all_connectors", lambda: {"boom": Boom()})
    c = Candidate(url="https://example.com/p", title="x", kind="web", connector="boom")
    monkeypatch.setattr(webpage, "fetch_url", lambda url, max_pages=None: Doc(url=url, title="w", text="t"))
    assert registry.fetch(c).title == "w"

    def bad(url, max_pages=None):
        raise RuntimeError("y")
    monkeypatch.setattr(webpage, "fetch_url", bad)
    assert registry.fetch(c) is None


def test_vault_fetch_returns_none_on_bad_file(data_dir):
    d = data_dir / "books" / "qm" / "notes"
    d.mkdir(parents=True)
    (d / "bad.md").write_bytes(b"---\n: [unclosed\n---\n\xff\xfe body")
    c = Candidate(url="vault://qm/notes/bad.md", title="t", kind="textbook", connector="vault")
    assert vault.fetch(c) is None


@respx.mock
def test_xai_search_records_usage_to_daily_file_and_quest_log(data_dir, monkeypatch):
    import json as _json
    from brain import quest, quest_stages, think
    _set_xai_key(monkeypatch, "k")
    respx.post("https://api.x.ai/v1/responses").mock(return_value=httpx.Response(200, json={
        "model": "grok-fast", "usage": {"input_tokens": 1_000_000, "output_tokens": 2_000_000},
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "[]"}]}]}))
    slug = quest.create("헬리콥터")["slug"]
    monkeypatch.setattr(xai_search, "CURRENT_LOG", quest.quest_dir(slug) / "log.jsonl")
    xai_search.search("q", "ko", 2)
    daily = [_json.loads(x) for x in think._usage_path().read_text("utf-8").splitlines()]
    assert daily == [dict(daily[0], kind="search", provider="xai", model="grok-fast",
                          **{"in": 1_000_000, "out": 2_000_000})]
    assert think.daily_count() == 0  # search rows do not eat the think cap
    assert quest_stages._estimate_cost(slug) == round(0.2 + 2 * 0.5, 4)
