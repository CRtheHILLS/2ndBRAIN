import hashlib, datetime as dt
from pathlib import Path
import pymupdf
from . import llm, store

fitz = pymupdf

IMG = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic"}

def _pdf_text(data: bytes) -> str:
    doc = fitz.open(stream=data, filetype="pdf"); out = []
    for i, page in enumerate(doc, 1):
        t = page.get_text().strip()
        if not t:  # scanned page → OCR
            t = llm.ocr_image(page.get_pixmap(dpi=150).tobytes("png"), "image/png")
        out.append(f"\n\n<!-- page {i} -->\n{t}")
    return "".join(out)

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
    if ext in IMG:
        kind, body = "image", llm.ocr_image(data, IMG[ext])
    elif ext == ".pdf":
        kind, body = "pdf", _pdf_text(data)
    else:
        kind, body = "text", data.decode("utf-8", errors="replace")
    (store.raw_dir(slug) / filename).write_bytes(data)  # keep original
    store.write_md(out, {"book": slug, "source": filename, "sha256": sha, "kind": kind,
                         "ingested_at": dt.datetime.now().isoformat(timespec="seconds")}, body)
    return out
