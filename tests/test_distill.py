import json
from brain import distill, ingest, store

FAKE = json.dumps({"summary": "요약", "concepts": [{"name": "엔트로피", "explain": "무질서도", "why_it_matters": "시간의 화살"}],
                   "quotes": [{"text": "별에서 왔다", "page": 3}], "cr_notes": ["멜로디로 표현?"]}, ensure_ascii=False)

def test_distill_writes_notes(data_dir, monkeypatch):
    store.upsert_book("cosmos", "코스모스")
    ingest.ingest_file("cosmos", "p.txt", b"text")
    monkeypatch.setattr(distill.llm, "complete", lambda s, u, smart=False: FAKE)
    d = distill.distill_book("cosmos")
    assert d["concepts"][0]["name"] == "엔트로피"
    assert (store.notes_dir("cosmos") / "concepts.md").read_text("utf-8").count("엔트로피") >= 1
    assert store.list_books()[0]["status"] == "distilled"
