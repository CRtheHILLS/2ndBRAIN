import httpx
import respx

from brain import ingest, llm, marks, ocr, store
from brain.config import get_settings

FULL = """앞 글 ==첫 밑줄 구절== 중간 ==별표
두 줄== 끝

## 표시 목록
- [밑줄] "첫 밑줄 구절"
- [별표] "별표 두 줄"
- [기타: 물결선] "끝"
## 독자 메모
- 여백: 이게 핵심!
## 쪽수
123
"""
NONE = "본문\n\n## 표시 목록\n- 없음\n## 독자 메모\n- 없음\n## 쪽수\n모름\n"
GEM = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"


def test_parse_marks_full():
    p = marks.parse_marks(FULL)
    assert p["marks"][0] == {"kind": "밑줄", "text": "첫 밑줄 구절"}
    assert [m["kind"] for m in p["marks"]] == ["밑줄", "별표", "기타: 물결선"]
    assert p["notes"] == ["여백: 이게 핵심!"] and p["page"] == "123"
    assert p["underline_spans"] == ["첫 밑줄 구절", "별표 두 줄"]
    assert marks.count_marks(FULL) == 3
    assert marks.mark_lines(FULL)[1] == "[별표] 별표 두 줄"


def test_parse_marks_none_and_legacy():
    p = marks.parse_marks(NONE)
    assert p == {"marks": [], "notes": [], "page": None, "underline_spans": []}
    assert marks.count_marks(NONE) == 0
    legacy = "앞 ==가 나== 뒤 ==다=="
    assert marks.parse_marks(legacy)["marks"] == [] and marks.parse_marks(legacy)["page"] is None
    assert marks.count_marks(legacy) == 2
    assert marks.mark_lines(legacy) == ["[밑줄] 가 나", "[밑줄] 다"]
    assert marks.count_marks("") == 0 and marks.count_marks(None) == 0


def test_prompt_has_format():
    for h in ("## 표시 목록", "## 독자 메모", "## 쪽수", "[밑줄]", "[형광펜]", "[별표]", "[괄호]",
              "[동그라미]", "[체크]", "[기타:", "- 없음", "==...=="):
        assert h in llm.OCR_SYSTEM


@respx.mock
def test_telegram_photo_in_clair_mode_skips_providers(data_dir, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("THINK_PROVIDERS", "gemini")
    get_settings.cache_clear()
    route = respx.post(GEM).mock(return_value=httpx.Response(200, json={}))
    p = ingest.ingest_file("book", "t1.jpg", b"\xff\xd8t", extra_meta={"via": "telegram"})
    assert store.read_md(p)[0]["ocr"] == "pending" and not route.called
    assert len(ocr.list_pending()) == 1
    get_settings.cache_clear()


@respx.mock
def test_upload_and_auto_mode_still_use_chain(data_dir, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("THINK_PROVIDERS", "gemini")
    get_settings.cache_clear()
    ok = {"candidates": [{"content": {"parts": [{"text": "읽음"}]}}]}
    route = respx.post(GEM).mock(return_value=httpx.Response(200, json=ok))
    assert store.read_md(ingest.ingest_file("book", "u.jpg", b"\xff\xd8u"))[0]["ocr"] == "done"
    assert route.call_count == 1
    monkeypatch.setenv("OCR_MODE", "auto")
    get_settings.cache_clear()
    p = ingest.ingest_file("book", "t2.jpg", b"\xff\xd8v", extra_meta={"via": "telegram"})
    assert store.read_md(p)[0]["ocr"] == "done" and route.call_count == 2
    get_settings.cache_clear()
