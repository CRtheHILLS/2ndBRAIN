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
    assert set(registry.all_connectors()) == {"wikipedia", "openalex", "arxiv", "pubmed", "semanticscholar"}
