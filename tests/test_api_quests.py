"""Quest HTTP routes (Task 13)."""
import pytest
from fastapi.testclient import TestClient

from brain import quest, think

H = {"X-Brain-Token": "test-token"}


@pytest.fixture
def started(monkeypatch):
    calls = []
    monkeypatch.setattr(quest, "start_background", lambda slug: calls.append(slug) or True)
    return calls


@pytest.fixture
def client(data_dir, started):
    from api.main import app
    with TestClient(app) as c:
        yield c


def _waiting_quest(monkeypatch):
    """A quest parked on the 'plan' task (no thinker available)."""
    def unavailable(*a, **k):
        raise think.ThinkUnavailable(["anthropic: no key"])
    monkeypatch.setattr(think, "think", unavailable)
    slug = quest.create("헬리콥터")["slug"]
    out = quest.run(slug)
    assert out["status"] == "waiting_thinker"
    return slug


def test_post_quest_creates_and_returns_url(client, started):
    r = client.post("/quests", headers=H, json={"sentence": "헬리콥터가 어떻게 뜨는지 배우고 싶어"})
    assert r.status_code == 200
    b = r.json()
    assert b["existing"] is False and b["status"] == "queued"
    assert b["url"] == f"/site/quests/{b['slug']}/index.html"
    assert started == [b["slug"]]


def test_post_same_sentence_returns_existing_without_restart(client, started):
    s = {"sentence": "헬리콥터가 어떻게 뜨는지 배우고 싶어"}
    first = client.post("/quests", headers=H, json=s).json()
    second = client.post("/quests", headers=H, json=s).json()
    assert second["existing"] is True and second["slug"] == first["slug"]
    assert started == [first["slug"]]


def test_post_blank_sentence_400(client):
    r = client.post("/quests", headers=H, json={"sentence": "   "})
    assert r.status_code == 400 and "문장" in r.json()["detail"]


def test_get_quest_404_and_bad_slug_400(client):
    assert client.get("/quests/quest-nope", headers=H).status_code == 404
    assert client.get("/quests/BAD_slug", headers=H).status_code == 400


def test_list_and_get(client):
    slug = client.post("/quests", headers=H, json={"sentence": "양자역학"}).json()["slug"]
    lst = client.get("/quests", headers=H).json()
    assert lst[0]["slug"] == slug and {"summary", "level", "days_requested"} <= set(lst[0])
    got = client.get(f"/quests/{slug}", headers=H).json()
    assert got["slug"] == slug and got["open_tasks"] == 0


def test_tasks_roundtrip(client, started, monkeypatch):
    slug = _waiting_quest(monkeypatch)
    tasks = client.get(f"/quests/{slug}/tasks", headers=H).json()
    assert [t["task_id"] for t in tasks] == ["plan"]
    assert client.get(f"/quests/{slug}", headers=H).json()["open_tasks"] == 1

    bad = client.post(f"/quests/{slug}/tasks/plan", headers=H, json={"output": {"kind": "topic"}})
    assert bad.status_code == 400 and "형식" in bad.json()["detail"]

    plan = {"kind": "topic", "title_ko": "헬리콥터", "title_en": "Helicopter",
            "one_line_goal": "뜨는 원리를 안다",
            "days": [{"n": 1, "big_idea": "양력",
                      "dots": [{"concept_ko": "양력", "concept_en": "lift", "queries_ko": ["양력"]}]}]}
    ok = client.post(f"/quests/{slug}/tasks/plan", headers=H, json={"output": plan})
    assert ok.status_code == 200 and ok.json()["accepted"] is True
    assert started[-1] == slug

    assert client.post(f"/quests/{slug}/tasks/nope", headers=H, json={"output": {}}).status_code == 404


def test_requires_token_on_all_quest_routes(client):
    calls = [
        ("post", "/quests", {"json": {"sentence": "x"}}),
        ("get", "/quests", {}),
        ("get", "/quests/quest-x", {}),
        ("get", "/quests/quest-x/tasks", {}),
        ("post", "/quests/quest-x/tasks/plan", {"json": {"output": {}}}),
        ("post", "/quests/quest-x/resume", {}),
        ("post", "/quests/quest-x/rerender?level=일반", {}),
    ]
    for method, url, kw in calls:
        assert getattr(client, method)(url, **kw).status_code == 401, url


def test_rerender_resets_teach_stage(client, started):
    slug = client.post("/quests", headers=H, json={"sentence": "발효"}).json()["slug"]
    d = quest.quest_dir(slug)
    (d / "tasks").mkdir(exist_ok=True)
    (d / "days").mkdir(exist_ok=True)
    (d / "tasks" / "teach-day-1.json").write_text("{}", "utf-8")
    (d / "tasks" / "plan.json").write_text("{}", "utf-8")
    (d / "days" / "1.json").write_text("{}", "utf-8")
    q = quest.load(slug)
    q.update(status="done", stage_done=["plan", "collect", "classify", "teach", "bridge", "archive"])
    quest.save(slug, q)
    started.clear()

    assert client.post(f"/quests/{slug}/rerender?level=쪽", headers=H).status_code == 400
    r = client.post(f"/quests/{slug}/rerender?level=전문", headers=H)
    assert r.status_code == 200 and r.json() == {"slug": slug, "status": "queued", "level": "전문"}
    q = quest.load(slug)
    assert q["stage_done"] == ["plan", "collect", "classify"] and q["level"] == "전문"
    assert q["status"] == "queued"
    assert not (d / "tasks" / "teach-day-1.json").exists() and not (d / "days" / "1.json").exists()
    assert (d / "tasks" / "plan.json").exists()
    assert started == [slug]


def test_resume_resets_time_budget_only_for_time_failures(client, started):
    slug = client.post("/quests", headers=H, json={"sentence": "광합성"}).json()["slug"]
    q = quest.load(slug)
    q.update(status="failed", error="실행 시간 예산 초과", budget={**q["budget"], "seconds": 9999.0})
    quest.save(slug, q)
    client.post(f"/quests/{slug}/resume", headers=H)
    assert quest.load(slug)["budget"]["seconds"] == 0.0

    q = quest.load(slug)
    q.update(status="failed", error="ValueError: x", budget={**q["budget"], "seconds": 77.0})
    quest.save(slug, q)
    client.post(f"/quests/{slug}/resume", headers=H)
    assert quest.load(slug)["budget"]["seconds"] == 77.0
