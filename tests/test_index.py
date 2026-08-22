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
