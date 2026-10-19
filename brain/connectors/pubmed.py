from __future__ import annotations

import xml.etree.ElementTree as ET

from . import base
from .base import Candidate, Doc

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _flat(el: ET.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


class PubMedConnector:
    name = "pubmed"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        ids = base.http_get(f"{EUTILS}/esearch.fcgi", params={
            "db": "pubmed", "term": query, "retmax": limit, "retmode": "json",
        }).json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        root = ET.fromstring(base.http_get(f"{EUTILS}/efetch.fcgi", params={
            "db": "pubmed", "id": ",".join(ids), "retmode": "xml",
        }).text)
        out = []
        for art in root.findall("PubmedArticle"):
            pmid = (art.findtext(".//MedlineCitation/PMID") or "").strip()
            if not pmid:
                continue
            year = _flat(art.find(".//PubDate/Year"))
            abstract = "\n".join(_flat(a) for a in art.findall(".//AbstractText"))
            out.append(Candidate(
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}", title=_flat(art.find(".//ArticleTitle")),
                kind="paper", snippet=abstract, year=int(year) if year.isdigit() else None,
                authority=0.85, connector=self.name, lang="en", extra={"pmid": pmid},
            ))
        return out

    def fetch(self, c: Candidate) -> Doc | None:
        if not c.snippet:
            return None
        return Doc(url=c.url, title=c.title, text=c.snippet, lang="en", kind="paper",
                   connector=self.name, meta=dict(c.extra))
