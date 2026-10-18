import json

from brain import graph, models, quest, quest_stages, store, think
from tests.test_render_quest import day_lesson, make_quest


class FakeThink:
    def __init__(self):
        self.users = []

    def __call__(self, kind, system, user, schema=None, *, smart=None, log_path=None):
        assert kind == "teach" and schema is models.DayLesson
        self.users.append(user)
        n = 1 if "Day 1/" in user else 2
        return think.ThinkResult(day_lesson(n), "fake", "fake-1", 1, 1, 0.0)


def test_stage_teach_writes_day_json_and_pages_and_lesson_nodes(data_dir, monkeypatch):
    fake = FakeThink()
    monkeypatch.setattr(think, "think", fake)
    slug = make_quest(days=())
    quest.save_ledger(slug, models.SourceLedger(sources=[models.SourceRecord(
        url="https://ex.org/lift", title="양력 문서", kind="encyclopedia", connector="wikipedia",
        score=0.9, day=1, dot="양력", lang="ko", why_picked="백과", fetched=True)]))
    quest_stages.stage_teach(slug)

    assert len(fake.users) == 2
    first, second = fake.users
    assert "헬리콥터" in first and "Day 1/총 2" in first and "양력" in first
    assert "https://ex.org/lift" in first and "뜨는 원리" in first  # ledger URL + honesty box
    assert "어제" in second and "위로 뜨는 힘" in second
    day1 = json.loads((quest.quest_dir(slug) / "days" / "day-1.json").read_text("utf-8"))
    cid = day1["dots"][0]["concept_id"]
    assert cid and graph.get_node(cid)["kind"] == "concept"
    assert (store.site_dir() / "quests" / slug / "day-1.html").exists()
    assert (store.site_dir() / "quests" / slug / "index.html").exists()
    assert graph.get_node(f"lesson:{slug}:day-1")["kind"] == "lesson"
    edges = graph.neighbors(f"lesson:{slug}:day-1")["edges"]
    assert any(e["rel"] == "taught_in" and e["src"] == cid for e in edges)
    assert any(e["rel"] == "in_book" and e["dst"] == f"book:{slug}" for e in edges)
    q = quest.load(slug)
    assert q["summary"]["pages"] == {"index": f"/site/quests/{slug}/index.html",
                                     "days": [f"/site/quests/{slug}/day-1.html",
                                              f"/site/quests/{slug}/day-2.html"]}
    assert q["summary"]["day1_big_idea"] == day1["big_idea_one_line"]
    assert q["budget"]["think_calls"] == 2


def test_teach_user_trims_excerpts_then_bridges_then_yesterday(data_dir, monkeypatch):
    slug = make_quest(days=())
    q = quest.load(slug)
    q["plan"]["bridge_hints"] = [{"target": "음악", "why": "브릿지 이유 " * 20}]
    prev = day_lesson(1)
    prev["dots"] = [{**prev["dots"][0], "concept_ko": f"어제점{i}", "one_line": "어제 한 줄 " * 10}
                    for i in range(5)]
    day2 = q["plan"]["days"][1]
    ledger = models.SourceLedger()

    def user(limit):
        monkeypatch.setattr(quest_stages, "TEACH_MAX_CHARS", limit)
        return quest_stages._teach_user(slug, q, day2, 1, prev, ledger)

    monkeypatch.setattr(quest_stages, "_dot_excerpts", lambda s, d: [])
    bare = user(100_000)
    monkeypatch.setattr(quest_stages, "_dot_excerpts", lambda s, d: ["   [출처: x] " + "발췌 " * 300] * 3)
    full = user(100_000)
    assert full.startswith("수준: 초등") and "브릿지 이유" in full and "어제점4" in full and "발췌 발췌" in full
    assert user(len(bare)) == bare  # 1st: all excerpts go, everything else stays
    m = user(len(bare) - 1)  # 2nd: bridge hints go
    assert "브릿지 이유" not in m and "어제점4" in m
    m = user(len(m) - 1)  # 3rd: yesterday's dot lines shrink from the end, its big idea stays
    assert "어제점4" not in m and "어제점0" in m and "- 큰 생각:" in m
    tiny = user(120)  # last resort tail cut never removes the level rules at the top
    assert len(tiny) <= 120 and tiny.startswith("수준: 초등\n초등학생도")


def test_day_lesson_grade_coercion():
    def grade(g):
        d = day_lesson()
        d["dots"][0]["evidence_grade"] = g
        return models.DayLesson.model_validate(d).dots[0].evidence_grade
    assert grade("연구 중") == "연구중"
    assert grade(" 확립됨 ") == "확립됨"
    assert grade("뭐지") == "연구중"
    assert models.SCHEMAS["DayLesson"] is models.DayLesson


def test_stage_teach_resumes_skipping_existing_days(data_dir, monkeypatch):
    fake = FakeThink()
    monkeypatch.setattr(think, "think", fake)
    slug = make_quest(days=(1,))
    quest_stages.stage_teach(slug)
    assert len(fake.users) == 1 and "Day 2/총 2" in fake.users[0]
    assert (store.site_dir() / "quests" / slug / "day-1.html").exists()
    assert (store.site_dir() / "quests" / slug / "day-2.html").exists()
