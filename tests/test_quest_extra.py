from brain import models, prompts, quest


def test_slug_collision_gets_suffix(data_dir, monkeypatch):
    monkeypatch.setattr(quest, "find_existing", lambda s: None)
    a = quest.create("바이올린")
    b = quest.create("바이올린")
    assert b["slug"] == a["slug"] + "-2"


def test_find_existing_across_dates(data_dir):
    quest.save("quest-20200101-old", {"slug": "quest-20200101-old", "sentence": "바이올린 배우고 싶어",
                                      "created_at": "2020-01-01T00:00:00"})
    quest.save("quest-20210101-new", {"slug": "quest-20210101-new", "sentence": "나 바이올린 알고 싶어",
                                      "created_at": "2021-01-01T00:00:00"})
    assert quest.find_existing("바이올린!") == "quest-20210101-new"


def test_days_level_no_false_positives(data_dir):
    q = quest.create("일반상대성이론 배우고 싶어")
    assert (q["level"], q["days_requested"]) == ("초등", 7)
    assert quest.create("10월 18일에 헬리콥터")["days_requested"] == 7
    assert quest.create("하루키 소설 읽고 싶어")["days_requested"] == 7
    assert quest.create("교양 수준으로 천문학")["level"] == "일반"


def test_save_is_atomic_no_tmp_left(data_dir):
    q = quest.create("바이올린")
    assert not (quest.quest_dir(q["slug"]) / "quest.json.tmp").exists()


def test_dot_validation():
    d = models.Dot(concept_ko="x", prefer_kinds=["paper", "bogus"])
    assert d.prefer_kinds == ["paper"] and d.evidence_grade_hint == "연구중"


def test_plan_system_content():
    s = prompts.plan_system(7)
    for w in ["확립됨", "연구중", "추측", "상술", "7일 뒤 CR은", "special_sources", "bridge_hints",
              "question", "큰 그림", "부품", "원리", "실제", "위험", "연결", "종합", "JSON 하나만"]:
        assert w in s, w
