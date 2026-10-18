"""Quest runner (Task 11): stage state machine + thinker-agnostic task protocol."""
import json
import re

import pytest

from brain import collect, config, graph, models, quest, quest_stages, store, think
from brain.connectors import registry
from brain.connectors.base import Candidate, Doc


def _plan_dict(days=2):
    return {
        "kind": "topic", "title_ko": "헬리콥터", "title_en": "Helicopter",
        "one_line_goal": "헬리콥터가 어떻게 뜨는지 안다",
        "days": [{"n": n, "big_idea": f"{n}일차 큰 그림",
                  "dots": [{"concept_ko": f"개념{n}{k}", "concept_en": f"concept{n}{k}",
                            "queries_ko": [f"질문{n}{k}"]} for k in (1, 2)]}
                 for n in range(1, days + 1)],
    }


def _batch_dict():
    return {"cards": [{"index": i, "title": f"자료{i}", "summary": "요약", "domain": "기술",
                       "concept_pairs": [{"ko": f"양력{i}", "en": f"lift{i}"}]}
                      for i in range(1, 6)]}


def _lesson_dict(n):
    return {"n": n, "big_idea_one_line": f"{n}일차 한 줄", "story_opening": "이야기",
            "dots": [{"concept_ko": f"개념{n}1", "one_line": "한 줄"}],
            "quiz": [{"q": "질문", "a": "답"}] * 3}


class FakeThink:
    def __init__(self):
        self.calls = []
        self.unavailable = False
        self.plan_days = 2
        self.classify_answers = []  # popped per classify call; None = unavailable

    def __call__(self, kind, system, user, schema=None, *, smart=None, log_path=None):
        self.calls.append(kind)
        scripted = kind == "classify" and bool(self.classify_answers)
        answer = self.classify_answers.pop(0) if scripted else None
        if self.unavailable or (scripted and answer is None):
            raise think.ThinkUnavailable(["anthropic: no key", "gemini: no key"])
        if kind == "teach":
            data = _lesson_dict(int(re.search(r"Day (\d+)/", user).group(1)))
        else:
            data = answer or (_plan_dict(self.plan_days) if kind == "plan" else _batch_dict())
        return think.ThinkResult(data, "fake", "fake-1", 10, 20, 0.01)


@pytest.fixture
def fakes(data_dir, monkeypatch):
    def search_all(query, lang, limit_per=5, names=None, timeout=25):
        c = Candidate(url=f"https://ex.org/{query}", title=f"{query} 문서", kind="encyclopedia",
                      authority=0.9, lang=lang, connector="wikipedia")
        return [c], {"wikipedia": "ok:1"}

    def fetch(c):
        return Doc(url=c.url, title=c.title, text="본문 " * 30, lang=c.lang, kind=c.kind,
                   connector=c.connector)

    monkeypatch.setattr(registry, "search_all", search_all)
    monkeypatch.setattr(registry, "fetch", fetch)
    fake = FakeThink()
    monkeypatch.setattr(think, "think", fake)
    return fake


def _raw_files(slug):
    return sorted(p.name for p in store.raw_dir(slug).glob("*.md"))


def test_run_plan_then_collect_then_classify_with_fakes(fakes):
    slug = quest.create("헬리콥터 배우고 싶어", days=2)["slug"]
    out = quest.run(slug)
    q = quest.load(slug)
    assert out["status"] == "done" == q["status"]
    assert q["stage_done"] == ["plan", "collect", "classify", "teach", "bridge", "archive"]
    assert len(q["plan"]["days"]) == 2
    assert len(_raw_files(slug)) >= 1
    assert graph.stats()["concepts"] >= 1
    assert q["summary"]["stage"] == "done"
    assert q["summary"]["n_concepts"] >= 1
    assert q["summary"]["n_sources"] == q["budget"]["sources"] >= 1
    assert q["summary"]["pages"]["index"] == f"/site/quests/{slug}/index.html"
    assert len(q["summary"]["pages"]["days"]) == 2 and q["summary"]["bridges"] == 0
    assert fakes.calls.count("teach") == 2
    assert q["summary"]["classify_remaining"] == 0
    assert q["budget"]["think_calls"] == len(fakes.calls)
    assert graph.get_node(f"quest:{slug}")["kind"] == "quest"
    assert quest.task_result(slug, "plan")["title_ko"] == "헬리콥터"
    assert quest.open_tasks(slug) == []


def test_think_unavailable_parks_and_submit_resumes(fakes):
    slug = quest.create("헬리콥터", days=2)["slug"]
    fakes.unavailable = True
    out = quest.run(slug)
    assert out["status"] == "waiting_thinker"
    assert out["summary"]["waiting_task"] == "plan"
    tasks = quest.open_tasks(slug)
    assert len(tasks) == 1
    t = tasks[0]
    assert (t["task_id"], t["kind"], t["schema"]) == ("plan", "plan", "QuestPlan")
    assert t["system"] and "헬리콥터" in t["user"] and "no key" in t["error"]
    assert quest.submit_task(slug, "plan", _plan_dict()) == {"accepted": True, "task_id": "plan"}
    assert quest.open_tasks(slug) == []
    out = quest.run(slug)  # plan comes from the submitted task; classify parks next
    assert out["stage_done"][:2] == ["plan", "collect"]
    assert out["status"] == "waiting_thinker"
    assert out["summary"]["waiting_task"].startswith("classify-")
    fakes.unavailable = False
    assert quest.run(slug)["status"] == "done"


def test_submitted_classify_task_is_used_on_resume(fakes):
    slug = quest.create("헬리콥터", days=2)["slug"]
    fakes.unavailable = True
    quest.run(slug)
    quest.submit_task(slug, "plan", _plan_dict())
    out = quest.run(slug)
    tid = out["summary"]["waiting_task"]
    quest.submit_task(slug, tid, _batch_dict())
    out = quest.run(slug)  # still no API thinker: only the submitted batch can help
    assert out["stage_done"][:3] == ["plan", "collect", "classify"]  # 4 raw files = one batch
    assert out["summary"]["n_concepts"] >= 1
    for n in (1, 2):  # teach parks per day and resumes from each submitted lesson
        assert out["status"] == "waiting_thinker" and out["summary"]["waiting_task"] == f"teach-day-{n}"
        quest.submit_task(slug, f"teach-day-{n}", _lesson_dict(n))
        out = quest.run(slug)
    assert out["status"] == "done"
    assert quest.open_tasks(slug) == []


def test_submit_invalid_output_keeps_task_open_with_error(fakes):
    slug = quest.create("헬리콥터", days=2)["slug"]
    fakes.unavailable = True
    quest.run(slug)
    bad = _plan_dict()
    del bad["days"]
    with pytest.raises(ValueError):
        quest.submit_task(slug, "plan", bad)
    task = json.loads(quest.task_path(slug, "plan").read_text("utf-8"))
    assert task["status"] == "open"
    assert task["error"] and "days" in task["error"]
    assert quest.open_tasks(slug)[0]["error"] == task["error"]
    with pytest.raises(KeyError):
        quest.submit_task(slug, "nope", {})


def test_run_is_resumable_and_skips_done_stages(fakes, monkeypatch):
    slug = quest.create("헬리콥터", days=2)["slug"]
    real_collect = collect.collect_quest

    def boom(s, p):
        raise RuntimeError("터짐")

    monkeypatch.setattr(collect, "collect_quest", boom)
    out = quest.run(slug)
    assert out["status"] == "failed" and "RuntimeError" in out["error"]
    assert out["stage_done"] == ["plan"]
    # collect finished outside the runner, then the quest is resumed
    q = quest.load(slug)
    real_collect(slug, models.QuestPlan.model_validate(q["plan"]))
    q["stage_done"].append("collect")
    quest.save(slug, q)
    before = _raw_files(slug)
    assert before
    calls = []
    monkeypatch.setattr(collect, "collect_quest", lambda s, p: calls.append(s))
    n_plan = fakes.calls.count("plan")
    out = quest.run(slug)
    assert out["status"] == "done"
    assert calls == []
    assert fakes.calls.count("plan") == n_plan
    assert _raw_files(slug) == before


def test_budget_think_calls_exceeded_parks(fakes, monkeypatch):
    monkeypatch.setenv("QUEST_MAX_THINK_CALLS", "0")
    config.get_settings.cache_clear()
    slug = quest.create("헬리콥터", days=2)["slug"]
    out = quest.run(slug)
    assert out["status"] == "waiting_thinker"
    assert fakes.calls == []
    assert "예산" in quest.open_tasks(slug)[0]["error"]


def test_time_budget_before_teach_fails(fakes):
    slug = quest.create("헬리콥터", days=2)["slug"]
    q = quest.load(slug)
    q["budget"]["seconds"] = 10_000
    quest.save(slug, q)
    out = quest.run(slug)
    assert out["status"] == "failed" and out["error"] == "실행 시간 예산 초과"


def test_time_budget_after_teach_finishes_done(fakes):
    slug = quest.create("헬리콥터", days=2)["slug"]
    quest.run(slug)
    q = quest.load(slug)
    q["stage_done"] = q["stage_done"][:4]  # through teach
    q["budget"]["seconds"] = 10_000
    quest.save(slug, q)
    out = quest.run(slug)
    assert out["status"] == "done" and out["summary"]["budget_exceeded"] is True


# --- review fixes -------------------------------------------------------------

def test_stale_classify_task_superseded_on_rebatch(fakes):
    fakes.plan_days = 4  # 8 dots -> 8 raw files -> batches of 5 + 3
    partial = {"cards": _batch_dict()["cards"][:3]}  # first batch: only 3 of 5 learned
    fakes.classify_answers = [partial, None, None]
    slug = quest.create("헬리콥터", days=4)["slug"]
    out = quest.run(slug)
    assert out["status"] == "waiting_thinker"
    assert out["summary"]["waiting_task"] == "classify-1"
    out = quest.run(slug)  # pending shifted -> new batch text -> new task
    assert out["status"] == "waiting_thinker"
    waiting = out["summary"]["waiting_task"]
    assert waiting == "classify-2"
    tasks = quest.open_tasks(slug)
    assert [t["task_id"] for t in tasks] == [waiting]
    old = json.loads(quest.task_path(slug, "classify-1").read_text("utf-8"))
    assert old["status"] == "superseded" and old["superseded_by"] == waiting


def test_submit_refuses_done_task_and_unknown_schema(fakes):
    slug = quest.create("헬리콥터", days=2)["slug"]
    quest.run(slug)
    with pytest.raises(ValueError, match="이미 끝난 과제"):
        quest.submit_task(slug, "plan", _plan_dict())
    p = quest.task_path(slug, "weird")
    p.write_text(json.dumps({"task_id": "weird", "schema": "Nope", "status": "open"}), "utf-8")
    with pytest.raises(ValueError, match="알 수 없는 스키마"):
        quest.submit_task(slug, "weird", {})


def test_think_or_cached_rejects_unregistered_schema(fakes):
    class Unregistered(models.BaseModel):
        x: int = 0

    slug = quest.create("헬리콥터", days=2)["slug"]
    with pytest.raises(ValueError, match="알 수 없는 스키마"):
        quest.think_or_cached(slug, "t", "classify", "s", "u", Unregistered)
    assert fakes.calls == []


def test_classify_id_uses_max_suffix(data_dir):
    slug = quest.create("헬리콥터", days=2)["slug"]
    d = quest.task_path(slug, "x").parent
    d.mkdir(parents=True)
    (d / "classify-0.json").write_text(json.dumps({"task_id": "classify-0", "user": "a"}), "utf-8")
    (d / "classify-5.json").write_text("{broken", "utf-8")
    assert quest_stages._classify_task_id(slug, "a") == "classify-0"
    assert quest_stages._classify_task_id(slug, "b") == "classify-6"


def test_plan_tokens_strip_particles_and_stopwords():
    assert quest_stages._tokens("나 헬리콥터를 완벽히 배우고 싶어") == ["헬리콥터"]
    assert quest_stages._tokens("양자역학의 역사와 철학") == ["양자역학", "역사", "철학"]


def test_stage_names_reexported_from_quest():
    assert quest.STAGE_FUNCS is quest_stages.STAGE_FUNCS
    assert quest.stage_plan is quest_stages.stage_plan

def test_full_run_creates_bridge_to_prior_book(fakes, monkeypatch):
    graph.ingest_card({"id": "aa" * 32, "book": "양자역학", "title": "각운동량 입문", "field_code": "B2",
                       "concept_pairs": [{"ko": "각운동량", "en": "Angular momentum"}]})
    reason = "자이로스코프가 쓰러지지 않는 건 각운동량이 지켜지기 때문이에요."
    plan = {"kind": "topic", "title_ko": "헬리콥터", "title_en": "Helicopter",
            "one_line_goal": "헬리콥터가 어떻게 뜨는지 안다",
            "days": [{"n": 1, "big_idea": "도는 것은 버틴다",
                      "dots": [{"concept_ko": "자이로스코프", "concept_en": "Gyroscope",
                                "queries_ko": ["자이로스코프"]}]}]}
    batch = {"cards": [{"index": i, "title": f"자료{i}", "summary": "요약", "domain": "과학",
                        "field_code": "B2",
                        "concept_pairs": [{"ko": "자이로스코프", "en": "Gyroscope"}]} for i in range(1, 6)]}
    lesson = {"n": 1, "big_idea_one_line": "도는 것은 버틴다", "story_opening": "이야기",
              "dots": [{"concept_ko": "자이로스코프", "one_line": "도는 바퀴"}],
              "quiz": [{"q": "질문", "a": "답"}] * 3}
    bridge_users = []

    def fake(kind, system, user, schema=None, *, smart=None, log_path=None):
        fakes.calls.append(kind)
        if kind == "bridge":
            bridge_users.append(user)
            data = {"verdicts": [{"src": "gyroscope", "dst": "angular-momentum", "connects": True,
                                  "rel": "bridge", "reason": reason}]}
        else:
            data = {"plan": plan, "classify": batch, "teach": lesson}[kind]
        return think.ThinkResult(data, "fake", "fake-1", 10, 20, 0.01)
    monkeypatch.setattr(think, "think", fake)

    slug = quest.create("헬리콥터 배우고 싶어", days=1)["slug"]
    assert quest.run(slug)["status"] == "done"
    assert fakes.calls.count("bridge") == 1 and "각운동량" in bridge_users[0]
    edges = graph.neighbors("gyroscope", rels=["bridge"])["edges"]
    assert [(e["src"], e["dst"], e["reason"]) for e in edges] == [("gyroscope", "angular-momentum", reason)]
    q = quest.load(slug)
    assert q["summary"]["bridges"] == 1
    assert q["summary"]["bridges_top"] == [{"a": "자이로스코프", "b": "각운동량", "reason": reason}]
    day = (store.site_dir() / "quests" / slug / "day-1.html").read_text("utf-8")
    assert "각운동량" in day and reason in day and "양자역학에서 배움" in day
    index = (store.site_dir() / "quests" / slug / "index.html").read_text("utf-8")
    assert "각운동량" in index
