import pytest

from brain import collect, models, quest, store
from brain.connectors import registry
from brain.connectors.base import Candidate, Doc


def cand(url, kind="web", authority=0.5, lang="ko", connector="x"):
    return Candidate(url=url, title=url, kind=kind, authority=authority, lang=lang, connector=connector)


def _plan(n_dots, specials=()):
    days = [models.DayPlan(n=1 + d // 5, big_idea="x",
                           dots=[models.Dot(concept_ko=f"c{d}", queries_ko=[f"q{d}"])])
            for d in range(n_dots)]
    return models.QuestPlan(kind="topic", title_ko="T", one_line_goal="g", days=days,
                            special_sources=[models.SpecialSource(name=f"s{i}", url=f"https://sp/{i}")
                                             for i in specials])


def _many(monkeypatch):
    def search_all(query, lang, **kw):
        return [cand(f"https://s/{query}/{i}", "encyclopedia" if i == 0 else "paper", 0.9 - i / 10)
                for i in range(3)], {"wikipedia": "ok:3"}

    monkeypatch.setattr(registry, "search_all", search_all)
    monkeypatch.setattr(registry, "fetch",
                        lambda c: Doc(url=c.url, title=c.title, text="본문 " * 10, lang="ko", kind=c.kind))


def test_budget_spread_over_all_dots_and_specials_run(data_dir, monkeypatch):
    _many(monkeypatch)
    monkeypatch.setattr(collect.webpage, "fetch_url",
                        lambda url, **kw: Doc(url=url, title="SP", text="공식 문서 " * 10, lang="ko"))
    q = quest.create("주제")
    ledger = collect.collect_quest(q["slug"], _plan(30, specials=range(2)))
    dots = {s.dot for s in ledger.sources if s.fetched and s.day > 0}
    assert dots == {f"c{d}" for d in range(30)}
    assert sum(1 for s in ledger.sources if s.day == 0 and s.fetched) == 2
    assert sum(s.fetched for s in ledger.sources) <= 45


def test_ledger_saved_after_each_dot_even_on_crash(data_dir, monkeypatch):
    _many(monkeypatch)
    real = registry.fetch

    def boom(c):
        if "/q1/" in c.url:
            raise RuntimeError("boom")
        return real(c)

    monkeypatch.setattr(registry, "fetch", boom)
    q = quest.create("주제")
    with pytest.raises(RuntimeError):
        collect.collect_quest(q["slug"], _plan(3))
    on_disk = quest.load_ledger(q["slug"])
    assert any(s.dot == "c0" and s.fetched for s in on_disk.sources)


def test_empty_plan_saves_ledger(data_dir):
    q = quest.create("주제")
    plan = models.QuestPlan(kind="topic", title_ko="T", one_line_goal="g", days=[])
    ledger = collect.collect_quest(q["slug"], plan)
    assert ledger.sources == []
    assert (quest.quest_dir(q["slug"]) / "sources.json").is_file()


def test_run_special_cases(data_dir, monkeypatch):
    docs = {"https://ok": Doc(url="https://ok", title="OK", text="내용 " * 10, lang="ko")}
    monkeypatch.setattr(collect.webpage, "fetch_url", lambda url, **kw: docs.get(url))
    sp = [models.SpecialSource(name="a", url="https://ok"), models.SpecialSource(name="b", url="https://dead"),
          models.SpecialSource(name="c", url="https://seen"), models.SpecialSource(name="d")]
    ledger = models.SourceLedger()
    n = collect.run_special("quest-t", sp, ledger, {"https://seen"})
    assert n == 1
    rec = ledger.sources[0]
    assert rec.day == 0 and rec.dot == "특별 출처" and rec.fetched
    meta = store.read_md(store.raw_dir("quest-t") / rec.raw_file)[0]
    assert meta["day"] == 0 and meta["dot"] == "특별 출처"
    assert [r["ok"] for r in ledger.special_tried] == [True, False, False, False]
    assert all(r["reason"] for r in ledger.special_tried[1:])
    l2 = models.SourceLedger()
    collect.run_special("quest-t", sp[:1], l2, set(), limit=0)
    assert l2.special_tried[0]["reason"] == "수집 예산 소진"


def test_failed_url_not_retried_by_other_dots(data_dir, monkeypatch):
    c = cand("https://dead", "encyclopedia", 0.9)
    monkeypatch.setattr(registry, "search_all", lambda q, lang, **kw: ([c], {}))
    monkeypatch.setattr(registry, "fetch", lambda c: None)
    used = set()
    collect.run_dot("quest-t", 1, models.Dot(concept_ko="a", queries_ko=["q"]), 1, models.SourceLedger(), used)
    l2 = models.SourceLedger()
    collect.run_dot("quest-t", 1, models.Dot(concept_ko="b", queries_ko=["q"]), 1, l2, used)
    assert l2.sources == []
