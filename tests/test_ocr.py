import json

import httpx
import pytest
import respx

from brain import catalog, ingest, ocr, store, think
from brain.config import get_settings

GEM = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
OK = {"candidates": [{"content": {"parts": [{"text": "읽은 글자"}]}}],
      "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7}}


@pytest.fixture
def gem(data_dir, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("THINK_PROVIDERS", "gemini")
    get_settings.cache_clear()
    yield data_dir
    get_settings.cache_clear()


@respx.mock
def test_gemini_success_returns_text_and_records_usage(gem):
    route = respx.post(GEM).mock(return_value=httpx.Response(200, json=OK))
    assert ocr.ocr_image(b"img", "image/jpeg") == "읽은 글자"
    req = route.calls[0].request
    assert req.headers["x-goog-api-key"] == "gk"
    body = json.loads(req.content)
    assert body["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"
    assert ocr.ocr_daily_count() == 1


@respx.mock
def test_gemini_503_raises_unavailable_with_reason(gem):
    respx.post(GEM).mock(return_value=httpx.Response(503))
    with pytest.raises(ocr.OcrUnavailable) as e:
        ocr.ocr_image(b"img", "image/jpeg")
    assert e.value.reasons == ["gemini: HTTP 503"]
    assert ocr.ocr_daily_count() == 0


def test_anthropic_not_called_when_not_in_providers(gem, monkeypatch):
    called = []
    monkeypatch.setattr(ocr.llm, "ocr_image", lambda b, m: called.append(1) or "x")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(ocr.OcrUnavailable):
        ocr.ocr_image(b"img", "image/jpeg")
    assert called == []


@respx.mock
def test_daily_cap(gem, monkeypatch):
    monkeypatch.setenv("OCR_DAILY_CAP", "1")
    get_settings.cache_clear()
    respx.post(GEM).mock(return_value=httpx.Response(200, json=OK))
    ocr.ocr_image(b"a", "image/jpeg")
    with pytest.raises(ocr.OcrUnavailable):
        ocr.ocr_image(b"b", "image/jpeg")


@respx.mock
def test_ingest_pending_then_complete(gem):
    respx.post(GEM).mock(return_value=httpx.Response(503))
    p = ingest.ingest_file("book", "p1.jpg", b"\xff\xd8x", extra_meta={"batch": "b1"})
    meta, body = store.read_md(p)
    assert meta["ocr"] == "pending" and meta["batch"] == "b1" and body == ""
    q = ocr.list_pending()
    assert len(q) == 1 and q[0]["id"] == catalog.make_id("book", "p1.jpg")
    assert q[0]["mime"] == "image/jpeg" and q[0]["image"].endswith("p1.jpg")
    assert not [i for i in catalog._read_queue() if i["id"] == q[0]["id"]]
    done = ocr.complete(q[0]["id"], "사람이 읽은 글")
    meta, body = store.read_md(p)
    assert meta["ocr"] == "done" and meta["batch"] == "b1" and body.strip() == "사람이 읽은 글"
    assert ocr.list_pending() == []
    assert [i for i in catalog._read_queue() if i["id"] == done["id"]]


@respx.mock
def test_ingest_ocr_done(gem):
    respx.post(GEM).mock(return_value=httpx.Response(200, json=OK))
    meta, body = store.read_md(ingest.ingest_file("book", "p2.jpg", b"\xff\xd8y"))
    assert meta["ocr"] == "done" and "읽은 글자" in body and ocr.list_pending() == []


def test_text_is_ocr_none(data_dir):
    assert store.read_md(ingest.ingest_file("book", "a.txt", b"hi"))[0]["ocr"] == "none"


def test_complete_unknown_raises(data_dir):
    with pytest.raises(KeyError):
        ocr.complete("nope", "x")


@respx.mock
def test_scanned_pdf_pending_once(gem):
    import pymupdf
    respx.post(GEM).mock(return_value=httpx.Response(503))
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    p = ingest.ingest_file("book", "s.pdf", doc.tobytes())
    meta, body = store.read_md(p)
    assert meta["ocr"] == "pending"
    assert "<!-- page 1: ocr pending -->" in body and "<!-- page 2: ocr pending -->" in body
    q = ocr.list_pending()
    assert len(q) == 1 and q[0]["mime"] == "application/pdf"


def test_ocr_rows_do_not_eat_think_quota(data_dir):
    from brain import think
    for _ in range(3):
        think.record_usage("ocr", "gemini", "m", 1, 1, 0.1)
    assert think.daily_count() == 0
    assert ocr.ocr_daily_count() == 3


def test_anthropic_listed_but_keyless_not_called(data_dir, monkeypatch):
    called = []
    monkeypatch.setattr(ocr.llm, "ocr_image", lambda b, m: called.append(1) or "x")
    monkeypatch.setenv("THINK_PROVIDERS", "anthropic")
    get_settings.cache_clear()
    with pytest.raises(ocr.OcrUnavailable) as e:
        ocr.ocr_image(b"img", "image/jpeg")
    assert called == [] and e.value.reasons == ["anthropic: 키 없음"]
    assert ocr.ocr_daily_count() == 0


@respx.mock
def test_extra_meta_cannot_overwrite_core(gem):
    respx.post(GEM).mock(return_value=httpx.Response(503))
    p = ingest.ingest_file("book", "m.jpg", b"\xff\xd8m", extra_meta={"sha256": "x", "ocr": "done", "k": 1})
    meta, _ = store.read_md(p)
    assert meta["sha256"] != "x" and meta["ocr"] == "pending" and meta["k"] == 1


@respx.mock
def test_reupload_pending_without_queue_entry_retries(gem):
    respx.post(GEM).mock(return_value=httpx.Response(503))
    p = ingest.ingest_file("book", "r.jpg", b"\xff\xd8r", extra_meta={"batch": "b"})
    eid = ocr.list_pending()[0]["id"]
    ocr.remove_pending(eid)
    respx.post(GEM).mock(return_value=httpx.Response(200, json=OK))
    ingest.ingest_file("book", "r.jpg", b"\xff\xd8r")
    meta, body = store.read_md(p)
    assert meta["ocr"] == "done" and meta["batch"] == "b" and "읽은 글자" in body
    # pending again, queue entry missing -> re-queued
    ocr.remove_pending(eid)
    respx.post(GEM).mock(return_value=httpx.Response(503))
    ingest.ingest_file("book", "r2.jpg", b"\xff\xd8r2")
    ocr.remove_pending(catalog.make_id("book", "r2.jpg"))
    ingest.ingest_file("book", "r2.jpg", b"\xff\xd8r2")
    assert [r["file"] for r in ocr.list_pending()] == ["r2.jpg"]


def test_complete_refuses_unfilled_skeleton(data_dir):
    md = store.raw_dir("b") / "x.md"
    store.write_md(md, {"book": "b", "source": "x.jpg", "sha256": "s", "kind": "image", "ocr": "pending"}, "")
    ocr.add_pending({"id": "e1", "book": "b", "file": "x.jpg", "path": str(md), "image": str(md), "mime": "image/jpeg"})
    skeleton = "<!-- 여기에 글자 -->\n\n## 표시 목록\n- 없음\n## 독자 메모\n\n## 쪽수\n모름\n"
    with pytest.raises(ValueError):
        ocr.complete("e1", skeleton)
    assert any(r["id"] == "e1" for r in ocr.list_pending())
    assert ocr.is_unfilled("\n## 표시 목록\n- 없음")
    assert not ocr.is_unfilled("본문 글자\n## 표시 목록\n- 없음")


def test_prompt_pins_korean_headings():
    from brain import llm
    assert "never translate or rename them" in llm.OCR_SYSTEM
    assert "No code fences" in llm.OCR_SYSTEM
