"""Connector base types: Candidate, Doc, Connector protocol, URL normalization, HTTP helper."""
from __future__ import annotations

import threading
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


_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True)
        return _client


def close_client() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


def http_get(url: str, params: dict | None = None, timeout: float = 20,
             headers: dict | None = None) -> httpx.Response:
    r = _get_client().get(url, params=params, timeout=timeout, headers=headers)
    r.raise_for_status()
    return r
