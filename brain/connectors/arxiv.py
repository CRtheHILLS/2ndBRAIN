from __future__ import annotations

import xml.etree.ElementTree as ET

from . import base
from .base import Candidate, Doc

NS = {"a": "http://www.w3.org/2005/Atom"}


def _text(entry: ET.Element, tag: str) -> str:
    el = entry.find(f"a:{tag}", NS)
    return " ".join((el.text or "").split()) if el is not None else ""


class ArxivConnector:
    name = "arxiv"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        r = base.http_get("https://export.arxiv.org/api/query",
                          params={"search_query": f"all:{query}", "max_results": limit})
        root = ET.fromstring(r.text)
        out = []
        for e in root.findall("a:entry", NS):
            published = _text(e, "published")
            out.append(Candidate(
                url=_text(e, "id"), title=_text(e, "title"), kind="paper",
                snippet=_text(e, "summary"),
                year=int(published[:4]) if published[:4].isdigit() else None,
                authority=0.75, connector=self.name, lang="en",
            ))
        return out

    def fetch(self, c: Candidate) -> Doc | None:
        # Atom summary only; the PDF is left to a later step.
        if not c.snippet:
            return None
        return Doc(url=c.url, title=c.title, text=c.snippet, lang="en", kind="paper", connector=self.name)
