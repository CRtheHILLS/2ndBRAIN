"""Source excerpts for think prompts (FTS over the volume's raw/notes files)."""
import os
import re
from pathlib import Path

from . import catalog, graph, index, store, vec
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


# --- hybrid retrieval (FTS + vector chunks + graph neighbours, fused with RRF) ----------

RRF_K = 60


def _graph_hits(query: str) -> list[dict]:
    """Lesson/source pages reachable one hop from the nodes whose labels match the query."""
    out: list[dict] = []
    for hit in graph.search_labels(query, 3):
        for n in graph.neighbors(hit["id"], 1)["nodes"]:
            nid, kind = n["id"], n.get("kind")
            if kind == "lesson":
                parts = nid.split(":")
                if len(parts) != 3:
                    continue
                slug = parts[1]
                path = f"site/quests/{slug}/{parts[2]}.html"
            elif kind == "source" and nid.startswith("src:"):
                entry = catalog.find_entry_by_prefix(nid[4:])
                if not entry or not entry.get("book"):
                    continue
                slug = entry["book"]
                stem = Path(entry.get("file") or "").stem
                if not stem:
                    continue
                path = f"{slug}/raw/{stem}.md"
            else:
                continue
            out.append({"slug": slug, "path": path, "text": n.get("summary") or "",
                        "title": n.get("label_ko") or nid})
    return out


def hybrid(query: str, k: int = 10, slug: str | None = None) -> list[dict]:
    def keep(s: str) -> bool:
        return not slug or s == slug

    lists: list[tuple[str, list[dict]]] = [
        ("fts", [h for h in index.search(query, k * 3) if keep(h["slug"])]),
        ("vec", [h for h in vec.similar_chunks(query, k * 3) if keep(h["slug"])]),
        ("graph", [h for h in _graph_hits(query) if keep(h["slug"])]),
    ]
    fused: dict[tuple[str, str], dict] = {}
    for via, hits in lists:
        for rank, h in enumerate(hits, start=1):
            key = (h["slug"], h["path"])
            row = fused.setdefault(key, {"text": "", "slug": h["slug"], "path": h["path"],
                                         "title": "", "score": 0.0, "via": []})
            row["score"] += 1.0 / (RRF_K + rank)
            if via not in row["via"]:
                row["via"].append(via)
            row["text"] = row["text"] or h.get("snippet") or h.get("text") or ""
            row["title"] = row["title"] or h.get("title") or ""
    root = get_settings().data_dir / "books"
    for row in fused.values():
        if not row["title"]:
            p = root / row["path"]
            if p.is_file():
                meta, _ = store.read_md(p)
                row["title"] = str(meta.get("title") or meta.get("source") or "")
            row["title"] = row["title"] or Path(row["path"]).stem
        row["snippet"] = row["text"]
    ranked = sorted(fused.values(), key=lambda r: (-r["score"], r["slug"], r["path"]))
    return ranked[:k]
