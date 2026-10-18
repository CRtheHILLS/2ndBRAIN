"""Archive stage + background execution (Task 13)."""
import json
import threading

from brain import models, quest, quest_stages, render


def test_stage_archive_fills_summary_and_cost(data_dir, monkeypatch):
    monkeypatch.setattr(render, "render_shelf", lambda: None)
    slug = quest.create("헬리콥터")["slug"]
    q = quest.load(slug)
    q["plan"] = {"one_line_goal": "헬리콥터가 어떻게 뜨는지 안다"}
    q["budget"]["seconds"] = 12.0
    quest.save(slug, q)
    ledger = quest.load_ledger(slug)
    ledger.new_connectors_tried = ["arxiv"]
    ledger.special_tried = [{"name": "NASA 문서", "ok": True}, {"name": "죽은 링크", "ok": False}]
    ledger.sources.append(models.SourceRecord(
        url="https://ex.org/a", title="a", kind="encyclopedia", connector="wikipedia", score=1.0,
        day=1, dot="d", lang="ko", why_picked="w", fetched=True))
    quest.save_ledger(slug, ledger)
    rows = [{"provider": "anthropic", "kind": "plan", "model": "m", "in": 1_000_000, "out": 100_000},
            {"provider": "xai", "kind": "classify", "model": "m", "in": 500_000, "out": 200_000},
            {"event": "stage_done"}]
    (quest.quest_dir(slug) / "log.jsonl").write_text("\n".join(json.dumps(r) for r in rows), "utf-8")

    quest_stages.stage_archive(slug)
    s = quest.load(slug)["summary"]
    assert s["cost_estimate"] == round(3 + 1.5 + 0.1 + 0.1, 4)
    assert s["n_sources"] == 1 and s["new_sources"] == ["arxiv", "NASA 문서"]
    assert s["one_line_goal"] == "헬리콥터가 어떻게 뜨는지 안다"
    assert s["elapsed_seconds"] >= 12.0 and s["stage"] == "done"
    assert s["bridges"] == 0 and s["bridges_top"] == [] and s["pages"] == {} and s["day1_big_idea"] == ""
    assert quest._summarize(slug)["cost_estimate"] == s["cost_estimate"]  # preserved, not reset


def test_start_background_runs_once(data_dir, monkeypatch):
    gate, ran = threading.Event(), []

    def fake_run(slug):
        ran.append(slug)
        gate.wait(5)

    monkeypatch.setattr(quest, "run", fake_run)
    assert quest.start_background("quest-x") is True
    assert quest.start_background("quest-x") is False  # still running
    gate.set()
    for t in threading.enumerate():
        if t.name == "quest-quest-x":
            t.join(timeout=5)
    assert ran == ["quest-x"] and not quest.is_running("quest-x")
