import csv, hashlib, datetime as dt
from io import BytesIO
from pathlib import Path
import pymupdf
from PIL import Image
from . import llm, store

fitz = pymupdf

IMG = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
       ".heic": "image/heic", ".heif": "image/heif"}
HEIC_EXTS = {".heic", ".heif"}

def _pdf_text(data: bytes) -> str:
    out = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, 1):
            t = page.get_text().strip()
            if not t:  # scanned page → OCR
                t = llm.ocr_image(page.get_pixmap(dpi=150).tobytes("png"), "image/png")
            out.append(f"\n\n<!-- page {i} -->\n{t}")
    return "".join(out)

def _to_jpeg(data: bytes, ext: str) -> bytes:
    """Convert image bytes (incl. HEIC/HEIF) to JPEG bytes for OCR."""
    if ext in HEIC_EXTS:
        import pillow_heif
        pillow_heif.register_heif_opener()
    img = Image.open(BytesIO(data)).convert("RGB")
    buf = BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()

def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("cp949")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")

def _escape_cell(v) -> str:
    s = "" if v is None else str(v)
    s = s.replace("|", "\\|")
    for nl in ("\r\n", "\r", "\n"):
        s = s.replace(nl, "<br>")
    return s

def _md_table(rows: list) -> str:
    rows = [list(r) for r in rows]
    if not rows:
        return ""
    header, *body = rows
    header = [_escape_cell(c) for c in header]
    lines = ["| " + " | ".join(header) + " |",
              "| " + " | ".join(["---"] * len(header)) + " |"]
    for row in body:
        lines.append("| " + " | ".join(_escape_cell(c) for c in row) + " |")
    return "\n".join(lines)

def _xlsx_tables(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
    try:
        parts = []
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            parts.append(f"## {ws.title}\n\n{_md_table(rows)}")
        return "\n\n".join(parts)
    finally:
        wb.close()

def _csv_table(data: bytes, stem: str) -> str:
    text = _decode_text(data)
    rows = list(csv.reader(text.splitlines()))
    return f"## {stem}\n\n{_md_table(rows)}"

def _sanitize_filename(filename: str) -> str:
    name = filename.replace("\\", "/").split("/")[-1]
    name = Path(name).name
    if not name or name in ("..", "."):
        raise ValueError(f"invalid filename: {filename!r}")
    return name


def ingest_file(slug: str, filename: str, data: bytes) -> Path:
    filename = _sanitize_filename(filename)
    sha = hashlib.sha256(data).hexdigest()
    ext = Path(filename).suffix.lower()
    out = store.raw_dir(slug) / (Path(filename).stem + ".md")
    if out.exists() and store.read_md(out)[0].get("sha256") == sha:
        return out
    (store.raw_dir(slug) / filename).write_bytes(data)  # keep original, before any llm call
    if ext in HEIC_EXTS:
        kind, body = "image", llm.ocr_image(_to_jpeg(data, ext), "image/jpeg")
    elif ext in IMG:
        kind, body = "image", llm.ocr_image(data, IMG[ext])
    elif ext == ".pdf":
        kind, body = "pdf", _pdf_text(data)
    elif ext == ".xlsx":
        kind, body = "table", _xlsx_tables(data)
    elif ext == ".csv":
        kind, body = "table", _csv_table(data, Path(filename).stem)
    else:
        kind, body = "text", _decode_text(data)
    store.write_md(out, {"book": slug, "source": filename, "sha256": sha, "kind": kind,
                         "ingested_at": dt.datetime.now().isoformat(timespec="seconds")}, body)
    return out
