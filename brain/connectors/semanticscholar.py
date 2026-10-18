from __future__ import annotations

import math

from . import base
from .base import Candidate, Doc


class SemanticScholarConnector:
    name = "semanticscholar"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        # HTTP errors (429/5xx) propagate; registry.search_all reports them as "error:<code>".
        data = base.http_get("https://api.semanticscholar.org/graph/v1/paper/search", params={
            "query": query, "limit": limit,
            "fields": "title,year,citationCount,url,abstract,openAccessPdf",
        }).json()
        out = []
        for p in data.get("data", []):
            cited = p.get("citationCount") or 0
            out.append(Candidate(
                url=p.get("url") or "", title=p.get("title") or "", kind="paper",
                snippet=p.get("abstract") or "", year=p.get("year"),
                authority=min(1.0, 0.7 + math.log10(cited + 1) / 10),
                connector=self.name, lang="en",
                extra={"cited_by": cited, "oa_pdf": (p.get("openAccessPdf") or {}).get("url")},
            ))
        return out

    def fetch(self, c: Candidate) -> Doc | None:
        if not c.snippet:
            return None
        return Doc(url=c.url, title=c.title, text=c.snippet, lang="en", kind="paper",
                   connector=self.name, meta=dict(c.extra))
