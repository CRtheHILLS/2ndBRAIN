"""Gemini text embeddings (768-d). Every failure mode returns None; never raises."""
import hashlib
import logging
from collections import OrderedDict

import httpx

from .config import get_settings

log = logging.getLogger(__name__)
DIM = 768
BATCH = 100
_CACHE_MAX = 2048
_cache: "OrderedDict[str, list[float]]" = OrderedDict()


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _remote(texts: list[str], key: str, model: str) -> list[list[float]] | None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
    body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]},
                          "outputDimensionality": DIM} for t in texts]}
    r = httpx.post(url, headers={"x-goog-api-key": key}, json=body, timeout=60)
    r.raise_for_status()
    vals = [e["values"] for e in r.json()["embeddings"]]
    if len(vals) != len(texts) or any(len(v) != DIM for v in vals):
        return None
    return vals


def embed(texts: list[str]) -> list[list[float]] | None:
    try:
        s = get_settings()
        if not texts:
            return []
        if not s.gemini_api_key:
            return None
        out: dict[int, list[float]] = {}
        todo: list[int] = []
        for i, t in enumerate(texts):
            hit = _cache.get(_key(t))
            if hit is not None:
                out[i] = hit
            else:
                todo.append(i)
        for start in range(0, len(todo), BATCH):
            idx = todo[start:start + BATCH]
            vals = _remote([texts[i] for i in idx], s.gemini_api_key, s.gemini_embed_model)
            if vals is None:
                return None
            for i, v in zip(idx, vals):
                out[i] = v
                _cache[_key(texts[i])] = v
                if len(_cache) > _CACHE_MAX:
                    _cache.popitem(last=False)
        return [out[i] for i in range(len(texts))]
    except Exception as e:  # network, auth, bad JSON ...
        log.warning("embed failed: %s", e)
        return None
