from brain import store


def test_write_read_roundtrip(data_dir):
    p = store.raw_dir("test-book") / "p1.md"
    store.write_md(p, {"book": "test-book", "page": 1}, "본문 ==밑줄== text")
    meta, body = store.read_md(p)
    assert meta["page"] == 1 and "==밑줄==" in body


def test_upsert_book_and_list(data_dir):
    store.upsert_book("cosmos", "코스모스", language="ko")
    assert store.list_books()[0]["title"] == "코스모스"
