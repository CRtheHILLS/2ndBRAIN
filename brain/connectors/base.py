"""Connector base types: Candidate, Doc, Connector protocol, URL normalization, HTTP helper."""
from __future__ import annotations

from typing import Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

UA = "2ndBRAIN/0.1 (+https://github.com/CRtheHILLS/2ndBRAIN)"

Kind = Literal["official", "encyclopedia", "paper", "textbook", "video", "web", "forum", "book"]


class Candidate(BaseModel):
    url: str
    title: str
    kind: Kind
    snippet: str = ""
    year: int | None = None
    authority: float = 0.5
    connector: str
    lang: str = ""
    extra: dict = Field(default_factory=dict)


class Doc(BaseModel):
    url: str
    title: str
    text: str
    lang: str = ""
    kind: Kind = "web"
    connector: str = ""
    meta: dict = Field(default_factory=dict)


class Connector(Protocol):
    name: str

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]: ...

    def fetch(self, c: Candidate) -> Doc | None: ...


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    for prefix in ("mobile.", "m.", "www."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    if parts.port:
        host = f"{host}:{parts.port}"
    query = urlencode([
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() != "fbclid"
    ])
    path = parts.path.rstrip("/")
    scheme = (parts.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    return urlunsplit((scheme, host, path, query, ""))


def http_get(url: str, params: dict | None = None, timeout: float = 20,
             headers: dict | None = None) -> httpx.Response:
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    r = httpx.get(url, params=params, timeout=timeout, headers=h, follow_redirects=True)
    r.raise_for_status()
    return r
