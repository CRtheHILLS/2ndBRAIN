"""Source excerpts for think prompts (FTS over raw/notes files and quest lessons)."""
import os
import re
from pathlib import Path

from . import catalog, graph, index, textutil, vec


def _window(body: str, query: str, chars: int) -> str:
    words = textutil.tokens(query) + [t for t in re.findall(r"\w+", query) if len(t) >= 2]
    terms = sorted(dict.fromkeys(words), key=len, reverse=True)
    pos = next((p for p in (body.find(t) for t in terms) if p >= 0), -1)
    if pos < 0:
        return body[:chars].strip()
    start = max(0, min(pos - chars // 3, len(body) - chars))
    return body[start:start + chars].strip()


def excerpts(query: str, slug: str | None = None, k: int = 3, chars: int = 400,
             lessons: bool = True) -> list[dict]:
    """Best FTS passages; ``lessons=False`` skips quest lesson docs (``<slug>/days/day-N.json``)."""
    out = []
    for hit in index.search(query, k * 3):
        path = hit["path"]
        if slug and not (path.startswith(f"{slug}/") or path.startswith(slug + os.sep)):
            continue
        if not lessons and index.is_lesson_path(path):
            continue
        doc = index.read_doc(path)
        if doc is None:
            continue
        title, body = doc
        out.append({"text": _window(body, query, chars), "slug": hit["slug"], "path": path, "title": title})
        if len(out) >= k:
            break
    return out


# --- hybrid retrieval (FTS + vector chunks + graph neighbours, fused with RRF) ----------

RRF_K = 60


def _graph_hits(query: str) -> list[dict]:
    """Lesson/source pages one hop from the nodes whose labels match a query word (top 3 per word)."""
    out: list[dict] = []
    seen_nodes, seen_paths = set(), set()
    words = textutil.tokens(query) or [query]
    for hit in (h for w in words for h in graph.search_labels(w, 3)):
        if not hit or hit["id"] in seen_nodes:
            continue
        seen_nodes.add(hit["id"])
        for n in graph.neighbors(hit["id"], 1)["nodes"]:
            nid, kind = n["id"], n.get("kind")
            if kind == "lesson":
                parts = nid.split(":")
                if len(parts) != 3:
                    continue
                slug = parts[1]
                path = f"{slug}/days/{parts[2]}.json"  # same key as the FTS lesson doc
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
            if path in seen_paths:
                continue
            seen_paths.add(path)
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
            if via == "vec" and h.get("text"):
                row["_vec_text"] = row.get("_vec_text") or h["text"]
            row["text"] = row["text"] or h.get("snippet") or h.get("text") or ""
            row["title"] = row["title"] or h.get("title") or ""
    for row in fused.values():
        vec_text = row.pop("_vec_text", "")
        # FTS snippets are a dozen trigram tokens with <mark>s: prefer the vec chunk or a real window
        doc = None if (vec_text and row["title"]) else index.read_doc(row["path"])
        if doc:
            row["title"] = row["title"] or doc[0]
        row["text"] = vec_text or (_window(doc[1], query, 400) if doc else "") or row["text"]
        row["title"] = row["title"] or Path(row["path"]).stem
        row["snippet"] = row["text"]
    ranked = sorted(fused.values(), key=lambda r: (-r["score"], r["slug"], r["path"]))
    return ranked[:k]
