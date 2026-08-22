from io import BytesIO
import openpyxl
import pymupdf
from PIL import Image
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

def test_path_traversal_filename_is_sanitized(data_dir):
    p = ingest.ingest_file("cosmos", "../../evil.txt", b"pwned")
    assert p.name == "evil.md"
    assert p.parent == store.raw_dir("cosmos")
    assert (store.raw_dir("cosmos") / "evil.txt").exists()
    assert not (data_dir / "evil.txt").exists()

def test_backslash_path_traversal_filename_is_sanitized(data_dir):
    p = ingest.ingest_file("cosmos", "..\\..\\evil2.txt", b"pwned")
    assert p.parent == store.raw_dir("cosmos")
    assert (store.raw_dir("cosmos") / "evil2.txt").exists()

def test_dotdot_filename_rejected(data_dir):
    import pytest
    with pytest.raises(ValueError):
        ingest.ingest_file("cosmos", "..", b"x")

def test_empty_filename_rejected(data_dir):
    import pytest
    with pytest.raises(ValueError):
        ingest.ingest_file("cosmos", "", b"x")

def test_raw_bytes_written_before_llm_call(data_dir, monkeypatch):
    def _boom(b, m):
        raise RuntimeError("llm exploded")
    monkeypatch.setattr(ingest.llm, "ocr_image", _boom)
    import pytest
    with pytest.raises(RuntimeError):
        ingest.ingest_file("cosmos", "IMG_2.jpg", b"\xff\xd8fake")
    assert (store.raw_dir("cosmos") / "IMG_2.jpg").exists()

def test_cp949_text_is_decoded(data_dir):
    data = "우주는 넓다".encode("cp949")
    p = ingest.ingest_file("cosmos", "cp949.txt", data)
    meta, body = store.read_md(p)
    assert meta["kind"] == "text" and "우주는 넓다" in body

def test_to_jpeg_converts_png_bytes_to_jpeg_magic_bytes(data_dir):
    buf = BytesIO()
    Image.new("RGB", (4, 4), color="red").save(buf, "PNG")
    out = ingest._to_jpeg(buf.getvalue(), ".png")
    assert out[:2] == b"\xff\xd8"

def test_pdf_ingest_extracts_text_and_ocrs_blank_page(data_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(ingest.llm, "ocr_image", lambda b, m: (calls.append(1), "OCR")[1])
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Hello Test Page")
    doc.new_page()  # blank page -> OCR
    pdf_bytes = doc.tobytes()
    doc.close()
    p = ingest.ingest_file("cosmos", "book.pdf", pdf_bytes)
    meta, body = store.read_md(p)
    assert meta["kind"] == "pdf"
    assert "Hello Test Page" in body
    assert "OCR" in body
    assert len(calls) == 1

def test_xlsx_ingest_produces_markdown_tables(data_dir):
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "용어"
    ws1.append(["용어", "풀이"])
    ws1.append(["a|b", "line1\nline2"])
    ws2 = wb.create_sheet("Sheet2")
    ws2.append(["x", "y"])
    ws2.append([1, 2])
    buf = BytesIO()
    wb.save(buf)
    p = ingest.ingest_file("cosmos", "glossary.xlsx", buf.getvalue())
    meta, body = store.read_md(p)
    assert meta["kind"] == "table"
    assert "## 용어" in body
    assert "## Sheet2" in body
    assert "a\\|b" in body
    assert "line1<br>line2" in body
    assert (store.raw_dir("cosmos") / "glossary.xlsx").exists()

def test_csv_ingest_produces_markdown_table_with_korean_utf8(data_dir):
    csv_bytes = "용어,풀이\n우주,넓다\n".encode("utf-8")
    p = ingest.ingest_file("cosmos", "terms.csv", csv_bytes)
    meta, body = store.read_md(p)
    assert meta["kind"] == "table"
    assert "## terms" in body
    assert "| 용어 | 풀이 |" in body
    assert "| 우주 | 넓다 |" in body
