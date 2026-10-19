from __future__ import annotations

import re
from urllib.parse import quote

from . import base
from .base import Candidate, Doc


def _api(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def _clean(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).replace("&quot;", '"').replace("&amp;", "&")


def _page_url(title: str, lang: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"


def fetch_title(title: str, lang: str) -> Doc | None:
    data = base.http_get(_api(lang), params={
        "action": "query", "prop": "extracts|links", "explaintext": 1, "titles": title,
        "pllimit": 30, "format": "json", "redirects": 1,
    }).json()
    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), None)
    if not page or not page.get("extract"):
        return None
    return Doc(
        url=_page_url(page.get("title", title), lang), title=page.get("title", title),
        text=page["extract"], lang=lang, kind="encyclopedia", connector="wikipedia",
        meta={"links": [lk["title"] for lk in page.get("links", [])][:30]},
    )


class WikipediaConnector:
    name = "wikipedia"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        lang = lang if lang in ("ko", "en") else "en"
        data = base.http_get(_api(lang), params={
            "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": limit,
        }).json()
        return [
            Candidate(
                url=_page_url(h["title"], lang), title=h["title"], kind="encyclopedia",
                snippet=_clean(h.get("snippet", "")), authority=0.9, connector=self.name, lang=lang,
            )
            for h in data.get("query", {}).get("search", [])
        ]

    def fetch(self, c: Candidate) -> Doc | None:
        return fetch_title(c.title, c.lang or "en")
