"""Quest runner (Task 11): stage state machine + thinker-agnostic task protocol."""
import json

import pytest

from brain import collect, config, graph, models, quest, store, think
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


class FakeThink:
    def __init__(self):
        self.calls = []
        self.unavailable = False

    def __call__(self, kind, system, user, schema=None, *, smart=None, log_path=None):
        self.calls.append(kind)
        if self.unavailable:
            raise think.ThinkUnavailable(["anthropic: no key", "gemini: no key"])
        data = _plan_dict() if kind == "plan" else _batch_dict()
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
    assert q["summary"]["pages"] == {} and q["summary"]["bridges"] == 0
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
    assert out["status"] == "done"  # 4 raw files = one batch, answered by the submission
    assert out["summary"]["n_concepts"] >= 1
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
