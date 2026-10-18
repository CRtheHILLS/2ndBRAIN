"""RAG answers: vault first, web only when the vault is thin, citations verified server-side."""
import hashlib
import re

from . import graph, models, retrieve, think
from .connectors import registry
from .prompts import ask_system

WEB_CHARS = 1200
LOW_SCORE = 0.02


def _hits(q: str) -> list[dict]:
    hybrid = getattr(retrieve, "hybrid", None)
    return list(hybrid(q, 8) if hybrid else retrieve.excerpts(q, k=8))


def _thin(hits: list[dict]) -> bool:
    if len(hits) < 3:
        return True
    scores = [h["score"] for h in hits if h.get("score") is not None]
    return bool(scores) and max(scores) < LOW_SCORE


def _web_passages(q: str) -> list[dict]:
    try:
        cands, _ = registry.search_all(q, "ko", 3, names=["wikipedia", "ddgs", "xai"])
    except Exception:  # noqa: BLE001 - web is best effort
        return []
    out = []
    for c in sorted(cands, key=lambda c: c.authority, reverse=True)[:3]:
        try:
            doc = registry.fetch(c)
        except Exception:  # noqa: BLE001
            doc = None
        text = (doc.text if doc else c.snippet) or ""
        if text.strip():
            out.append({"text": text[:WEB_CHARS], "title": (doc.title if doc else c.title) or c.title,
                        "url": (doc.url if doc else c.url) or c.url, "slug": "", "path": "", "web": True})
    return out


def _record_question(q: str, passages: list[dict]) -> None:
    qid = "q:" + hashlib.sha256(q.encode("utf-8")).hexdigest()[:8]
    graph.upsert_node(qid, "question", q[:120])
    low = q.lower()
    inside = sorted((n for n in graph.by_kind("concept", limit=10**6)
                     if len(n["label_ko"]) >= 2 and n["label_ko"].lower() in low),
                    key=lambda n: -len(n["label_ko"]))
    targets = [n["id"] for n in inside[:3]]
    for n in graph.search_labels(q, 3):
        if n["kind"] == "concept" and n["id"] not in targets:
            targets.append(n["id"])
    for p in passages:
        if len(targets) >= 3:
            break
        if p.get("web") or not p.get("slug"):
            continue
        for sid in graph.node_ids_in_book(p["slug"], "concept")[:3]:
            if sid not in targets and len(targets) < 3:
                targets.append(sid)
    for t in targets[:3]:
        graph.add_edge(qid, t, "asked")


def ask(q: str, mode: str = "auto", level: str = "초등") -> dict:
    hits = _hits(q)
    web_used = mode == "web" or (mode == "auto" and _thin(hits))
    passages = [] if mode == "web" else [dict(h, web=False) for h in hits]
    if web_used:
        passages += _web_passages(q)
    lines = []
    for n, p in enumerate(passages, 1):
        if p.get("web"):
            src = f"(웹) {p['title']} | {p['url']}"
        else:
            src = f"{p.get('title', '')} | {p.get('slug', '')}/{p.get('path', '')}"
        lines.append(f"[{n}] (출처: {src})\n{p.get('text', '')}")
    user = (f"질문: {q}\n\n[자료]\n" + ("\n\n".join(lines) if lines else "(자료 없음)")
            + "\n\n위 자료 번호만 근거로 JSON으로 답하라.")
    res = think.think("ask", ask_system(level), user, models.AskAnswer)
    data = dict(res.data)
    cited: list[int] = []
    for m in re.findall(r"\[(\d+)\]", data.get("answer_html", "")):
        n = int(m)
        if 1 <= n <= len(passages) and n not in cited:
            cited.append(n)
    data["citations"] = [models.Citation(
        title=passages[n - 1].get("title", ""), url=passages[n - 1].get("url", ""),
        slug=passages[n - 1].get("slug", ""), path=passages[n - 1].get("path", "")).model_dump()
        for n in cited]
    n_vault = sum(1 for p in passages if not p.get("web"))
    data["used_vault_ratio"] = n_vault / len(passages) if passages else 0.0
    _record_question(q, passages)
    data["hits"] = len(hits)
    data["web_used"] = web_used
    return data
