from __future__ import annotations

import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import httpx

from .base import Candidate, Connector, Doc


def all_connectors() -> dict[str, Connector]:
    from .arxiv import ArxivConnector
    from .openalex import OpenAlexConnector
    from .pubmed import PubMedConnector
    from .semanticscholar import SemanticScholarConnector
    from .wikipedia import WikipediaConnector
    from .ddgs_web import DdgsConnector
    from .vault import VaultConnector
    from .webpage import WebpageConnector
    from .xai_search import XaiConnector
    from .youtube import YouTubeConnector

    return {c.name: c for c in (
        WikipediaConnector(), OpenAlexConnector(), ArxivConnector(),
        PubMedConnector(), SemanticScholarConnector(),
        WebpageConnector(), YouTubeConnector(), DdgsConnector(), XaiConnector(), VaultConnector(),
    )}


def fetch(c: Candidate) -> Doc | None:
    from . import vault, webpage, youtube

    try:
        if youtube.video_id(c.url):
            return youtube.fetch(c)
        if c.url.startswith("vault://"):
            return vault.fetch(c)
        conn = all_connectors().get(c.connector)
        doc = conn.fetch(c) if conn else None
    except Exception:
        doc = None
    if doc:
        return doc
    try:
        return webpage.fetch_url(c.url)
    except Exception:
        return None


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return str(exc.response.status_code)
    return f"{type(exc).__name__}: {exc}"


def search_all(query: str, lang: str, limit_per: int = 5, names: Iterable[str] | None = None,
               timeout: float = 25) -> tuple[list[Candidate], dict[str, str]]:
    conns = all_connectors()
    if names is not None:
        conns = {n: conns[n] for n in names if n in conns}
    candidates: list[Candidate] = []
    status: dict[str, str] = {}
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        futures = {n: pool.submit(c.search, query, lang, limit_per) for n, c in conns.items()}
        deadline = time.monotonic() + timeout
        for name, fut in futures.items():
            try:
                found = fut.result(timeout=max(0.0, deadline - time.monotonic()))
                candidates.extend(found)
                status[name] = f"ok:{len(found)}"
            except FutureTimeout:
                status[name] = "error:timeout"
            except Exception as exc:  # one connector must not sink the others
                status[name] = f"error:{_describe(exc)}"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return candidates, status
