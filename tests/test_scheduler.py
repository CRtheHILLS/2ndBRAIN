"""Retry scheduler (Task 13)."""
import datetime as dt
import json

import pytest

from brain import quest, scheduler


@pytest.fixture
def resumed(monkeypatch):
    calls = []
    monkeypatch.setattr(quest, "resume", lambda slug: calls.append(slug) or {"slug": slug})
    return calls


def _make(sentence, status, updated_ago_min=0, created_ago_h=0):
    slug = quest.create(sentence)["slug"]
    q = quest.load(slug)
    now = dt.datetime.now()
    q["status"] = status
    q["created_at"] = (now - dt.timedelta(hours=created_ago_h)).isoformat(timespec="seconds")
    q["updated_at"] = (now - dt.timedelta(minutes=updated_ago_min)).isoformat(timespec="seconds")
    # written directly: quest.save() would stamp updated_at with the current time
    (quest.quest_dir(slug) / "quest.json").write_text(json.dumps(q, ensure_ascii=False), "utf-8")
    return slug


def test_tick_resumes_stale_waiting_quest(data_dir, resumed):
    slug = _make("헬리콥터", "waiting_thinker", updated_ago_min=45, created_ago_h=2)
    out = scheduler.tick()
    assert out["resumed"] == [slug] and resumed == [slug]


def test_tick_skips_recent_and_expired(data_dir, resumed):
    _make("양자역학", "waiting_thinker", updated_ago_min=5, created_ago_h=1)
    _make("블랙홀", "waiting_thinker", updated_ago_min=600, created_ago_h=60)
    _make("재즈", "done", updated_ago_min=600)
    out = scheduler.tick()
    assert out["resumed"] == [] and resumed == []
    assert len(out["skipped"]) == 3 and all(isinstance(s, str) for s in out["skipped"])


def test_tick_recovers_running_without_thread(data_dir, resumed):
    slug = _make("발효", "running")
    live = _make("광합성", "running")
    quest._running.add(live)
    try:
        out = scheduler.tick()
    finally:
        quest._running.discard(live)
    assert out["resumed"] == [slug] and resumed == [slug]


def test_tick_survives_bad_quest_file(data_dir, resumed):
    bad = quest.quests_root() / "quest-broken"
    bad.mkdir()
    (bad / "quest.json").write_text("{not json", "utf-8")
    slug = _make("화산", "waiting_thinker", updated_ago_min=45)
    assert scheduler.tick()["resumed"] == [slug]


def test_tick_survives_resume_error(data_dir, monkeypatch):
    a = _make("지진", "waiting_thinker", updated_ago_min=45)
    b = _make("쓰나미", "waiting_thinker", updated_ago_min=45)
    done = []

    def boom(slug):
        if slug == a:
            raise RuntimeError("x")
        done.append(slug)

    monkeypatch.setattr(quest, "resume", boom)
    out = scheduler.tick()
    assert b in done and b in out["resumed"]
