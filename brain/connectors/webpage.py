from __future__ import annotations

import re

import pymupdf
import trafilatura

from brain.config import get_settings

from . import base
from .base import Candidate, Doc


def download(url: str, max_bytes: int = 15_000_000) -> tuple[bytes, str]:
    return base.http_download(url, max_bytes, timeout=30)


def extract_html(html: bytes | str, url: str) -> tuple[str, str]:
    # raw bytes let trafilatura's charset detection handle EUC-KR etc.
    text = trafilatura.extract(html, url=url, include_comments=False) or ""
    title = ""
    meta = trafilatura.extract_metadata(html)
    if meta is not None and meta.title:
        title = meta.title
    if not title:
        s = html if isinstance(html, str) else html.decode("utf-8", errors="replace")
        m = re.search(r"<title[^>]*>(.*?)</title>", s, re.I | re.S)
        title = m.group(1).strip() if m else ""
    return title, text


def extract_pdf(data: bytes, max_pages: int) -> str:
    out = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, 1):
            if i > max_pages:
                break
            out.append(f"\n\n<!-- page {i} -->\n{page.get_text().strip()}")
    return "".join(out)


def fetch_url(url: str, max_pages: int | None = None) -> Doc | None:
    if max_pages is None:
        max_pages = get_settings().quest_max_pdf_pages
    try:
        data, ctype = download(url)
        is_pdf = "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf") or data[:5] == b"%PDF-"
        if is_pdf:
            title, text = url.rsplit("/", 1)[-1], extract_pdf(data, max_pages)
        else:
            title, text = extract_html(data, url)
    except Exception:
        return None
    if not text.strip():
        return None
    return Doc(url=url, title=title or url, text=text, connector="webpage", kind="web")


class WebpageConnector:
    name = "webpage"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        return []

    def fetch(self, c: Candidate) -> Doc | None:
        return fetch_url(c.url)
