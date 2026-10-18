from brain import index, retrieve, store


def test_excerpts_filters_slug_and_trims(data_dir):
    filler = "가나다라마바사 " * 100
    store.write_md(store.raw_dir("heli") / "lift.md", {"title": "양력 백과"},
                   filler + "양력은 날개가 공기를 아래로 밀 때 생기는 힘이다. " + filler)
    store.write_md(store.raw_dir("other") / "lift.md", {"title": "다른 책"}, "양력 이야기 " * 20)
    index.rebuild()

    out = retrieve.excerpts("양력", slug="heli", k=3, chars=120)
    assert out and all(e["slug"] == "heli" for e in out)
    e = out[0]
    assert e["title"] == "양력 백과"
    assert e["path"].startswith("heli")
    assert "양력" in e["text"] and len(e["text"]) <= 120

    both = retrieve.excerpts("양력", k=5)
    assert {e["slug"] for e in both} == {"heli", "other"}
    assert len(retrieve.excerpts("양력", k=1)) == 1
