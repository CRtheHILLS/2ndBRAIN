import json

from brain import models, quest, render, store

PLAN = {
    "kind": "topic", "title_ko": "헬리콥터", "title_en": "Helicopter",
    "one_line_goal": "2일 뒤 CR은 헬리콥터가 뜨는 원리를 설명할 수 있다",
    "honesty": {"learnable_by_reading": ["뜨는 원리"], "needs_practice": ["실제 조종"],
                "hype_warning": []},
    "days": [{"n": 1, "big_idea": "날개가 공기를 밀면 뜬다",
              "dots": [{"concept_ko": "양력", "concept_en": "lift"}]},
             {"n": 2, "big_idea": "꼬리 날개가 몸통을 잡아 준다",
              "dots": [{"concept_ko": "반토크", "concept_en": "anti-torque"}]}],
    "bridge_hints": [],
}


def day_lesson(n=1, svg='<svg viewBox="0 0 200 120"><circle cx="50" cy="50" r="20"/></svg>'):
    return {
        "n": n, "big_idea_one_line": f"{n}일차: 날개가 공기를 아래로 밀면 위로 뜬다",
        "story_opening": "피아노 건반을 세게 누르면 소리가 커지죠.",
        "dots": [{"concept_id": "lift", "concept_ko": "양력", "one_line": "위로 뜨는 힘",
                  "picture_svg": svg, "emoji": "🚁", "analogy": "부채질", "real_example": "새",
                  "why_it_matters": "이게 없으면 못 떠요", "evidence_grade": "확립됨",
                  "sources": ["https://ex.org/lift"]}],
        "quiz": [{"q": "왜 뜰까?", "a": "공기를 밀어서", "why": "작용 반작용"}] * 3,
        "say_it_yourself": "양력을 내 말로?", "link_yesterday": "", "clair_one_liner": "잘했어요!",
    }


def make_quest(slug="heli", days=(1,)):
    q = {"slug": slug, "sentence": "헬리콥터 배우고 싶어", "days_requested": 2, "level": "초등",
         "status": "done", "stage_done": [], "plan": PLAN, "created_at": "2026-10-18T09:00:00",
         "updated_at": "2026-10-18T09:00:00", "started_by": "cli", "error": None, "summary": {},
         "budget": {"think_calls": 0, "sources": 0, "seconds": 0.0}}
    quest.save(slug, q)
    d = quest.quest_dir(slug) / "days"
    d.mkdir(parents=True, exist_ok=True)
    for n in days:
        (d / f"day-{n}.json").write_text(json.dumps(day_lesson(n), ensure_ascii=False), "utf-8")
    return slug


def test_render_day_contains_sections_and_single_level(data_dir):
    slug = make_quest(days=(1, 2))
    html = render.render_quest_day(slug, 1).read_text("utf-8")
    for s in ("오늘의 퀴즈", "<details", "grade-확립됨", "클레어의 한마디", "다른 때 배운 것과 잇기",
              "아직 없어요", "https://ex.org/lift", "<circle", "Day 1", "day-2.html"):
        assert s in html, s
    assert 'role="tab"' not in html and "초등" not in html
    assert (store.site_dir() / "brain.css").exists()


def test_svg_sanitizer_drops_script(data_dir):
    good = '<svg viewBox="0 0 200 120"><rect width="10" height="10"/></svg>'
    assert render._sanitize_svg(good) == good
    for bad in ('<svg><script>alert(1)</script></svg>', '<svg onload="x()"></svg>',
                '<svg><a href="https://evil"><text>x</text></a></svg>',
                '<svg><foreignObject></foreignObject></svg>', "<b>not svg</b>"):
        assert render._sanitize_svg(bad) == ""
    slug = make_quest()
    (quest.quest_dir(slug) / "days" / "day-1.json").write_text(
        json.dumps(day_lesson(1, svg='<svg onload="x()"></svg>'), ensure_ascii=False), "utf-8")
    html = render.render_quest_day(slug, 1).read_text("utf-8")
    assert "onload" not in html and "🚁" in html


def test_render_quest_index_lists_days_honesty_sources(data_dir):
    slug = make_quest()
    quest.save_ledger(slug, models.SourceLedger(
        sources=[models.SourceRecord(url="https://ex.org/lift", title="양력 문서", kind="encyclopedia",
                                     connector="wikipedia", score=0.9, day=1, dot="양력", lang="ko",
                                     why_picked="믿을 만한 백과", fetched=True)],
        vault_hits=[{"url": "https://ex.org/old", "title": "예전 자료", "dot": "양력", "day": 1,
                     "score": 0.8}],
        new_connectors_tried=["arxiv"]))
    html = render.render_quest(slug).read_text("utf-8")
    for s in ("헬리콥터", PLAN["one_line_goal"], "읽어서 되는 것", "몸으로 해야 하는 것",
              "날개가 공기를 밀면 뜬다", "꼬리 날개가 몸통을 잡아 준다", "day-1.html",
              "1 / 2", "양력 문서", "https://ex.org/lift", "믿을 만한 백과",
              "이미 내 서재에 있던 자료", "예전 자료", "이번에 새로 시도한 출처", "arxiv",
              "../../index.html"):
        assert s in html, s
    assert "과장 주의" not in html  # empty list is hidden


def test_shelf_shows_quests(data_dir):
    make_quest()
    html = render.render_shelf().read_text("utf-8")
    assert "퀘스트" in html and "헬리콥터" in html and "quests/heli/index.html" in html
    assert "끝났어요" in html
