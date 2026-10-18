import hashlib

from brain import catalog, collect, config, models, store
from brain.connectors import registry
from brain.connectors.base import Candidate, Doc


def cand(url, kind="web", authority=0.5, lang="ko", connector="x", title=None):
    return Candidate(url=url, title=title or url, kind=kind, authority=authority,
                     lang=lang, connector=connector)


def test_score_weights():
    off = collect.score(cand("https://a.org/1", "official", 0.8), "ko", [])
    enc = collect.score(cand("https://a.org/2", "encyclopedia", 0.8), "ko", [])
    vid = collect.score(cand("https://a.org/3", "video", 0.8), "ko", [])
    assert off > enc > vid
    assert collect.score(cand("https://a.org/4", lang="en"), "ko", []) < collect.score(cand("https://a.org/5"), "ko", [])
    assert collect.score(cand("https://a.org/6", "paper"), "ko", ["paper"]) > collect.score(cand("https://a.org/7", "paper"), "ko", [])


def test_dedup_by_url_and_title():
    a = cand("https://www.example.com/x?utm_source=q", "web", 0.9, title="Quantum entanglement basics")
    b = cand("https://example.com/x", "web", 0.3, title="other")
    c = cand("https://other.org/y", "web", 0.2, title="Quantum entanglement basics!")
    d = cand("https://z.org/z", "web", 0.5, title="Totally different")
    out = collect.dedup([b, a, c, d])
    assert [x.url for x in out] == [a.url, d.url]


def test_pick_for_dot_quota_rules():
    enc = cand("https://e", "encyclopedia", 0.9, lang="en")
    pap = cand("https://p", "paper", 0.8, lang="en")
    vid = cand("https://v", "video", 0.9, lang="en")
    vid2 = cand("https://v2", "video", 0.9, lang="en")
    web = cand("https://w", "web", 0.9, lang="en")
    out = collect.pick_for_dot([vid, vid2, web, pap, enc], 2)
    assert {c.url for c in out} == {"https://e", "https://p"}
    big = collect.pick_for_dot([vid, vid2, web, pap, enc], 5)
    assert sum(c.kind == "video" for c in big) == 1 and len(big) == 4


def test_pick_swaps_in_korean():
    enc = cand("https://e", "encyclopedia", 0.9, lang="en")
    pap = cand("https://p", "paper", 0.8, lang="en")
    ko = cand("https://k", "web", 0.5, lang="ko")
    out = collect.pick_for_dot([enc, pap, ko], 2)
    assert any(c.lang == "ko" for c in out) and len(out) == 2


def _fake(monkeypatch, cands_by_query=None, texts=None):
    def search_all(query, lang, limit_per=5, names=None, timeout=25):
        found = (cands_by_query or {}).get((query, lang), [])
        return found, {"wikipedia": f"ok:{len(found)}", "arxiv": "error:timeout"}

    def fetch(c):
        t = (texts or {}).get(c.url, "본문 " * 20)
        return None if t is None else Doc(url=c.url, title=c.title, text=t, lang=c.lang, kind=c.kind, connector=c.connector)

    monkeypatch.setattr(registry, "search_all", search_all)
    monkeypatch.setattr(registry, "fetch", fetch)


def test_run_dot_writes_raw_and_registers(data_dir, monkeypatch):
    e = cand("https://ko.wikipedia.org/wiki/A", "encyclopedia", 0.9, connector="wikipedia", title="A")
    _fake(monkeypatch, {("얽힘", "ko"): [e]})
    dot = models.Dot(concept_ko="얽힘", queries_ko=["얽힘"])
    ledger = models.SourceLedger()
    n = collect.run_dot("quest-t", 2, dot, 2, ledger, set())
    assert n == 1
    sha8 = hashlib.sha256(e.url.encode()).hexdigest()[:8]
    p = store.raw_dir("quest-t") / f"src-d02-{sha8}.md"
    meta, body = store.read_md(p)
    assert meta["book"] == "quest-t" and meta["source"] == e.url and meta["day"] == 2
    assert meta["dot"] == "얽힘" and meta["kind"] == "encyclopedia" and meta["connector"] == "wikipedia"
    assert len(meta["sha256"]) == 64 and body.strip()
    assert {"score", "lang", "title", "fetched_at"} <= set(meta)
    assert len(catalog.pending()) == 1
    assert len(ledger.sources) == 1 and ledger.sources[0].fetched
    assert ledger.connector_status["wikipedia"] == {"ok": 1, "error": 0, "results": 1}
    assert ledger.connector_status["arxiv"]["error"] == 1


def test_run_dot_truncates_and_retries_next_best(data_dir, monkeypatch):
    monkeypatch.setenv("QUEST_MAX_DOC_CHARS", "50")
    config.get_settings.cache_clear()
    bad = cand("https://bad", "encyclopedia", 0.9)
    good = cand("https://good", "paper", 0.8)
    _fake(monkeypatch, {("q", "ko"): [bad, good]}, {"https://bad": None, "https://good": "가" * 500})
    ledger = models.SourceLedger()
    n = collect.run_dot("quest-t", 1, models.Dot(concept_ko="c", queries_ko=["q"]), 1, ledger, set())
    assert n == 1
    assert [s.fetched for s in ledger.sources] == [False, True]
    assert ledger.sources[0].reason
    assert ledger.sources[1].chars == 50


def test_run_dot_respects_used_urls_and_vault(data_dir, monkeypatch):
    a = cand("https://a", "encyclopedia", 0.9)
    v = cand("vault://books/x/raw/1.md", "book", 0.9, connector="vault")
    _fake(monkeypatch, {("q", "ko"): [a, v]})
    ledger = models.SourceLedger()
    used = {"https://a"}
    n = collect.run_dot("quest-t", 1, models.Dot(concept_ko="c", queries_ko=["q"]), 2, ledger, used)
    assert n == 0
    assert len(ledger.vault_hits) == 1
    assert catalog.pending() == []


def test_run_dot_fallback_queries(data_dir, monkeypatch):
    calls = []

    def search_all(query, lang, **kw):
        calls.append((query, lang))
        return [], {}

    monkeypatch.setattr(registry, "search_all", search_all)
    collect.run_dot("quest-t", 1, models.Dot(concept_ko="얽힘", concept_en="entanglement"), 2,
                    models.SourceLedger(), set())
    assert calls == [("얽힘", "ko"), ("entanglement", "en")]


def test_collect_quest_stops_at_max_sources(data_dir, monkeypatch):
    monkeypatch.setenv("QUEST_MAX_SOURCES", "3")
    config.get_settings.cache_clear()

    def search_all(query, lang, **kw):
        return [cand(f"https://s/{query}/{i}", "encyclopedia" if i == 0 else "paper", 0.9 - i / 10)
                for i in range(3)], {"wikipedia": "ok:3"}

    monkeypatch.setattr(registry, "search_all", search_all)
    monkeypatch.setattr(registry, "fetch", lambda c: Doc(url=c.url, title=c.title, text="본문 " * 10, lang="ko", kind=c.kind))
    days = [models.DayPlan(n=d, big_idea="x", dots=[models.Dot(concept_ko=f"c{d}{i}", queries_ko=[f"q{d}{i}"]) for i in range(3)])
            for d in (1, 2)]
    plan = models.QuestPlan(kind="topic", title_ko="T", one_line_goal="g", days=days)
    from brain import quest
    q = quest.create("주제")
    ledger = collect.collect_quest(q["slug"], plan)
    assert sum(s.fetched for s in ledger.sources) == 3
    assert len(list(store.raw_dir(q["slug"]).glob("*.md"))) == 3
    assert ledger.new_connectors_tried == ["wikipedia"]
    assert quest.load_ledger(q["slug"]).new_connectors_tried == ["wikipedia"]
