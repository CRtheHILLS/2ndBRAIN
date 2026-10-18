from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import httpx

from .base import Candidate, Connector


def all_connectors() -> dict[str, Connector]:
    from .arxiv import ArxivConnector
    from .openalex import OpenAlexConnector
    from .pubmed import PubMedConnector
    from .semanticscholar import SemanticScholarConnector
    from .wikipedia import WikipediaConnector

    return {c.name: c for c in (
        WikipediaConnector(), OpenAlexConnector(), ArxivConnector(),
        PubMedConnector(), SemanticScholarConnector(),
    )}


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
        for name, fut in futures.items():
            try:
                found = fut.result(timeout=timeout)
                candidates.extend(found)
                status[name] = f"ok:{len(found)}"
            except FutureTimeout:
                status[name] = "error:timeout"
            except Exception as exc:  # one connector must not sink the others
                status[name] = f"error:{_describe(exc)}"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return candidates, status
