from __future__ import annotations

import math

from . import base
from .base import Candidate, Doc


def abstract_from_inverted_index(idx: dict | None) -> str:
    if not idx:
        return ""
    words: dict[int, str] = {}
    for word, positions in idx.items():
        for p in positions:
            words[p] = word
    return " ".join(words[i] for i in sorted(words))


class OpenAlexConnector:
    name = "openalex"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        data = base.http_get("https://api.openalex.org/works",
                             params={"search": query, "per-page": limit}).json()
        out = []
        for w in data.get("results", []):
            cited = w.get("cited_by_count") or 0
            doi = w.get("doi") or ""
            oa_pdf = (w.get("open_access") or {}).get("oa_url")
            url = (w.get("primary_location") or {}).get("landing_page_url") or doi or w.get("id", "")
            out.append(Candidate(
                url=url, title=w.get("title") or "", kind="paper",
                snippet=abstract_from_inverted_index(w.get("abstract_inverted_index")),
                year=w.get("publication_year"),
                authority=min(1.0, 0.7 + math.log10(cited + 1) / 10),
                connector=self.name, lang="en",
                extra={"cited_by": cited, "oa_pdf": oa_pdf, "doi": doi},
            ))
        return out

    def fetch(self, c: Candidate) -> Doc | None:
        # Abstract only; Candidate.extra["oa_pdf"] is left for a later PDF-fetching step.
        text = c.snippet
        if not text:
            return None
        return Doc(url=c.url, title=c.title, text=text, lang=c.lang, kind="paper",
                   connector=self.name, meta=dict(c.extra))
