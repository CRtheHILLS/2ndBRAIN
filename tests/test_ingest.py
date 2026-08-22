from brain import ingest, store

def test_text_passthrough(data_dir):
    p = ingest.ingest_file("cosmos", "ch1.txt", "우주는 넓다".encode())
    meta, body = store.read_md(p)
    assert meta["kind"] == "text" and "우주는 넓다" in body

def test_image_uses_ocr(data_dir, monkeypatch):
    monkeypatch.setattr(ingest.llm, "ocr_image", lambda b, m: "OCR 결과 ==밑줄==")
    p = ingest.ingest_file("cosmos", "IMG_1.jpg", b"\xff\xd8fake")
    assert "==밑줄==" in store.read_md(p)[1]

def test_idempotent(data_dir):
    a = ingest.ingest_file("cosmos", "a.txt", b"same")
    b = ingest.ingest_file("cosmos", "a.txt", b"same")
    assert a == b
