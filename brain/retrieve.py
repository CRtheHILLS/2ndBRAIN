"""Source excerpts for think prompts (FTS over the volume's raw/notes files)."""
import os
import re
from pathlib import Path

from . import index, store
from .config import get_settings


def _window(body: str, query: str, chars: int) -> str:
    terms = sorted((t for t in re.findall(r"\w+", query) if len(t) >= 2), key=len, reverse=True)
    pos = next((p for p in (body.find(t) for t in terms) if p >= 0), -1)
    if pos < 0:
        return body[:chars].strip()
    start = max(0, min(pos - chars // 3, len(body) - chars))
    return body[start:start + chars].strip()


def excerpts(query: str, slug: str | None = None, k: int = 3, chars: int = 400) -> list[dict]:
    root = get_settings().data_dir / "books"
    out = []
    for hit in index.search(query, k * 3):
        path = hit["path"]
        if slug and not (path.startswith(f"{slug}/") or path.startswith(slug + os.sep)):
            continue
        p = root / path
        if not p.is_file():
            continue
        meta, body = store.read_md(p)
        out.append({"text": _window(body, query, chars), "slug": hit["slug"], "path": path,
                    "title": str(meta.get("title") or meta.get("source") or Path(path).stem)})
        if len(out) >= k:
            break
    return out
