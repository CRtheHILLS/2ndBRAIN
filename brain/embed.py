"""Gemini text embeddings (768-d). Every failure mode returns None; never raises."""
import hashlib
import logging
import math
from collections import OrderedDict

import httpx

from .config import get_settings

log = logging.getLogger(__name__)
DIM = 768
BATCH = 100
_CACHE_MAX = 2048
_cache: "OrderedDict[str, list[float]]" = OrderedDict()


def _key(text: str, task: str) -> str:
    return task + ":" + hashlib.sha1(text.encode("utf-8")).hexdigest()


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def _remote(texts: list[str], key: str, model: str, task: str) -> list[list[float]] | None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
    task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
    body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]},
                          "taskType": task_type, "outputDimensionality": DIM} for t in texts]}
    r = httpx.post(url, headers={"x-goog-api-key": key}, json=body, timeout=60)
    r.raise_for_status()
    vals = [e["values"] for e in r.json()["embeddings"]]
    if len(vals) != len(texts) or any(len(v) != DIM for v in vals):
        return None
    return [_normalize(v) for v in vals]  # truncated Gemini vectors are not unit length; vec0 uses L2


def embed(texts: list[str], task: str = "document") -> list[list[float]] | None:
    """Unit-length 768-d vectors. ``task`` is "document" (indexing) or "query" (searching)."""
    try:
        s = get_settings()
        if not texts:
            return []
        if not s.gemini_api_key:
            return None
        out: dict[int, list[float]] = {}
        todo: list[int] = []
        for i, t in enumerate(texts):
            hit = _cache.get(_key(t, task))
            if hit is not None:
                out[i] = hit
            else:
                todo.append(i)
        for start in range(0, len(todo), BATCH):
            idx = todo[start:start + BATCH]
            vals = _remote([texts[i] for i in idx], s.gemini_api_key, s.gemini_embed_model, task)
            if vals is None:
                return None
            for i, v in zip(idx, vals):
                out[i] = v
                _cache[_key(texts[i], task)] = v
                if len(_cache) > _CACHE_MAX:
                    _cache.popitem(last=False)
        return [out[i] for i in range(len(texts))]
    except Exception as e:  # network, auth, bad JSON ...
        log.warning("embed failed: %s", e)
        return None
