from brain import index, ingest, store

def test_rebuild_and_search(data_dir):
    store.upsert_book("cosmos", "코스모스")
    ingest.ingest_file("cosmos", "p.txt", "엔트로피는 무질서도의 척도다".encode())
    assert index.rebuild() == 1
    hits = index.search("무질서도")
    assert hits and hits[0]["slug"] == "cosmos"

def test_search_with_double_quote_does_not_raise(data_dir):
    store.upsert_book("cosmos", "코스모스")
    ingest.ingest_file("cosmos", "p.txt", "엔트로피는 무질서도의 척도다".encode())
    index.rebuild()
    hits = index.search('무질서도"')
    assert isinstance(hits, list)

def test_search_short_query_falls_back_to_like(data_dir):
    store.upsert_book("cosmos", "코스모스")
    ingest.ingest_file("cosmos", "p.txt", "우주는 넓다".encode())
    index.rebuild()
    hits = index.search("우주")
    assert hits and hits[0]["slug"] == "cosmos"

def test_search_multi_term_query_finds_doc_with_both_words(data_dir):
    store.upsert_book("cosmos", "코스모스")
    ingest.ingest_file("cosmos", "p.txt", "엔트로피는 무질서도의 척도다".encode())
    index.rebuild()
    hits = index.search("엔트로피 척도")
    assert hits and hits[0]["slug"] == "cosmos"


def _seed_vault():
    import json
    from brain import quest
    from tests.test_render_quest import day_lesson, make_quest
    store.upsert_book("aero", "항공")
    store.write_md(store.raw_dir("aero") / "lift.md", {"title": "양력 백과"},
                   "양력은 날개가 공기를 아래로 밀 때 생기는 힘이다. 비행기와 헬리콥터가 뜨는 까닭이다.")
    make_quest("heli", days=(1,))
    lesson = day_lesson(1)
    lesson["dots"][0]["analogy"] = "회전날개는 부채질처럼 바람을 아래로 보낸다"
    (quest.quest_dir("heli") / "days" / "day-1.json").write_text(json.dumps(lesson, ensure_ascii=False), "utf-8")


def test_search_tokenizes_korean_question_with_particles(data_dir):
    _seed_vault()
    assert index.rebuild() == 2
    hits = index.search("양력은 왜 생기는 거야?")
    assert hits and hits[0]["path"].replace("\\", "/") == "aero/raw/lift.md"
    # AND finds nothing (회전날개 only in the lesson, 비행기 only in the raw doc) -> OR finds both
    paths = {h["path"].replace("\\", "/") for h in index.search("회전날개랑 비행기는 뭐가 달라?")}
    assert paths == {"aero/raw/lift.md", "heli/days/day-1.json"}


def test_lesson_json_is_indexed_and_resolvable(data_dir):
    from brain import retrieve
    _seed_vault()
    index.rebuild()
    hits = index.search("부채질처럼 바람을")
    assert [h["slug"] for h in hits] == ["heli"] and hits[0]["path"] == "heli/days/day-1.json"
    ex = retrieve.excerpts("회전날개가 뭐야", k=3)
    assert ex and ex[0]["path"] == "heli/days/day-1.json" and "부채질" in ex[0]["text"]
    assert "1일차" in ex[0]["title"]
    assert retrieve.excerpts("회전날개가 뭐야", k=3, lessons=False) == []
    out = retrieve.hybrid("회전날개는 무엇인가요", k=5)
    assert out and out[0]["path"] == "heli/days/day-1.json" and out[0]["title"]
