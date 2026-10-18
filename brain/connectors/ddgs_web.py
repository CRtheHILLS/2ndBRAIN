from __future__ import annotations

from urllib.parse import urlsplit

from ddgs import DDGS

from .base import Candidate, Doc, Kind


def guess_kind(url: str) -> Kind:
    host = (urlsplit(url).hostname or "").lower()
    if "youtube.com" in host or host == "youtu.be":
        return "video"
    if host.endswith((".gov", ".edu", ".go.kr", ".ac.kr")):
        return "official"
    if host.startswith("blog.") or any(k in host for k in ("tistory", "brunch", "reddit")):
        return "forum"
    return "web"


def search(query: str, lang: str, limit: int) -> list[Candidate]:
    try:
        rows = DDGS().text(query, max_results=limit, region="kr-kr" if lang == "ko" else "wt-wt")
    except Exception:
        return []
    return [
        Candidate(url=r["href"], title=r.get("title", ""), kind=guess_kind(r["href"]),
                  snippet=r.get("body", ""), connector="ddgs", lang=lang)
        for r in (rows or []) if r.get("href")
    ]


class DdgsConnector:
    name = "ddgs"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        return search(query, lang, limit)

    def fetch(self, c: Candidate) -> Doc | None:
        return None
