import re

from brain import models, prompts, quest


def test_create_extracts_days_and_level(data_dir):
    q = quest.create("3일 만에 전문가 수준으로 헬리콥터")
    assert q["days_requested"] == 3
    assert q["level"] == "전문"
    assert q["status"] == "queued"
    assert quest.load(q["slug"])["sentence"] == "3일 만에 전문가 수준으로 헬리콥터"


def test_create_defaults(data_dir):
    q = quest.create("나 헬리콥터 운전 배우고 싶어")
    assert q["days_requested"] == 7
    assert q["level"] == "초등"
    assert q["existing"] is False
    assert quest.create("하루 만에 양자역학")["days_requested"] == 1
    assert quest.create("역사", days=5, level="일반")["level"] == "일반"


def test_slug_safe_for_quotes_emoji_long(data_dir):
    s = '"' + "양자역학 😀 'quantum' " * 20 + "!!"
    slug = quest.slug_for(s)
    assert len(slug) <= 60
    assert re.fullmatch(r"[0-9a-z가-힣-]+", slug)
    assert not slug.endswith("-")


def test_same_sentence_returns_existing(data_dir):
    a = quest.create("나 헬리콥터 운전 배우고 싶어")
    b = quest.create("헬리콥터 운전 배우고 싶어!")
    assert b["existing"] is True
    assert b["slug"] == a["slug"]
    assert quest.find_existing("저 헬리콥터 운전 알고 싶어요?") == a["slug"]
    assert quest.find_existing("바이올린") is None
    assert len(quest.list_quests()) == 1


def test_log_and_ledger_roundtrip(data_dir):
    q = quest.create("바이올린")
    quest.log(q["slug"], event="x")
    assert "x" in (quest.quest_dir(q["slug"]) / "log.jsonl").read_text("utf-8")
    assert quest.load_ledger(q["slug"]).sources == []
    quest.save_ledger(q["slug"], models.SourceLedger(new_connectors_tried=["wikipedia"]))
    assert quest.load_ledger(q["slug"]).new_connectors_tried == ["wikipedia"]


def test_plan_system_fills_placeholders():
    s = prompts.plan_system(5)
    assert "{DAYS}" not in s and "{FIELDS}" not in s
    assert "5일 뒤 CR은" in s
