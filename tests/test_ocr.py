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
