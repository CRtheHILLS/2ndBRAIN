"""Knowledge catalog + learn queue.

Every file that lands in a book's ``raw/`` directory gets registered here, so
nothing CR ever uploads goes unclassified.  A background/manual pass then asks
a cheap model to file each item like a librarian would: title, summary, domain,
tags, canonical concepts, named entities.  The canonical concept names are the
seed of the future dot-to-dot concept graph.

Layout under ``DATA_DIR/catalog``::

    queue.jsonl        append-only learn queue (one JSON object per line)
    entries/<id>.json  learned entry (queue fields + classification)
    graph.json         last built concept graph
"""

import datetime as dt
import hashlib
import itertools
import json
from pathlib import Path

from . import llm, store
from .config import get_settings

DOMAINS = ["과학", "역사", "종교", "철학", "심리", "경제", "기술", "예술", "동물", "건강", "기타"]

BODY_LIMIT = 15000

CATALOG_SYSTEM = """너는 2nd BRAIN의 사서(librarian)다. 자료 한 편을 읽고 서가에 꽂을 분류 카드를 만든다.
JSON 객체 하나만 출력한다. 마크다운 펜스, 설명 문장, 인사말은 절대 붙이지 않는다.

{"title": "<자료 제목, 한국어. 원문에 없으면 내용으로 지어낸다>",
 "summary": "<200자 이내 한국어 요약>",
 "domain": "<과학|역사|종교|철학|심리|경제|기술|예술|동물|건강|기타 중 정확히 하나>",
 "tags": ["<한국어 태그 3~8개>"],
 "concepts": ["<정규화된 한국어 개념명 3~10개>"],
 "entities": ["<인물·장소·작품 등 고유명사, 없으면 빈 배열>"]}

concepts는 반드시 표준형(canonical)으로 적는다: "얽힘 현상"이 아니라 "양자 얽힘",
"다윈의 진화론"이 아니라 "진화론", "블랙홀 현상"이 아니라 "블랙홀".
같은 개념은 자료가 달라도 언제나 똑같은 이름이어야 개념 그래프가 이어진다.
모든 값은 한국어로 쓴다(고유명사는 원어 병기 허용)."""


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def catalog_dir() -> Path:
    p = get_settings().data_dir / "catalog"
    p.mkdir(parents=True, exist_ok=True)
    return p


def queue_path() -> Path:
    return catalog_dir() / "queue.jsonl"


def entries_dir() -> Path:
    p = catalog_dir() / "entries"
    p.mkdir(parents=True, exist_ok=True)
    return p


def entry_path(entry_id: str) -> Path:
    return entries_dir() / f"{entry_id}.json"


def graph_path() -> Path:
    return catalog_dir() / "graph.json"


def make_id(book: str, filename: str) -> str:
    return hashlib.sha256(f"{book}/{filename}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# queue
# ---------------------------------------------------------------------------

def _read_queue() -> list[dict]:
    p = queue_path()
    if not p.is_file():
        return []
    out, seen = [], set()
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or "id" not in item:
            continue
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    return out


def _append_queue(item: dict) -> None:
    with queue_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def queued() -> list[dict]:
    """Every queue entry, deduped by id, in insertion order."""
    return _read_queue()


def register(book: str, filename: str, raw_path: Path, sha256: str) -> dict:
    """Put one raw file on the learn queue. Idempotent by (book, filename)."""
    entry_id = make_id(book, filename)
    for item in _read_queue():
        if item["id"] == entry_id:
            return item
    learned = entry_path(entry_id)
    if learned.is_file():
        try:
            return json.loads(learned.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    item = {
        "id": entry_id,
        "book": book,
        "file": filename,
        "path": str(raw_path),
        "sha256": sha256,
        "added_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
    }
    _append_queue(item)
    return item


def is_learned(entry_id: str) -> bool:
    return entry_path(entry_id).is_file()


def pending() -> list[dict]:
    """Queue entries that have no learned entry file yet."""
    return [i for i in _read_queue() if not is_learned(i["id"])]


def learned() -> list[dict]:
    out = []
    for p in sorted(entries_dir().glob("*.json")):
        try:
            d = json.loads(p.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def get_entry(entry_id: str) -> dict | None:
    p = entry_path(entry_id)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return d if isinstance(d, dict) else None


# ---------------------------------------------------------------------------
# learning
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> dict | None:
    """Same balanced-brace salvage distill uses: take the outermost {...}."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        d = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def _str_list(v, limit: int) -> list[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        if isinstance(x, dict):
            x = x.get("name") or x.get("title") or ""
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out[:limit]


def _raw_path(entry: dict) -> Path | None:
    p = Path(entry["path"]) if entry.get("path") else None
    if p is not None and p.is_file():
        return p
    # the volume may have moved since the item was queued — fall back to the book
    book, name = entry.get("book"), entry.get("file")
    if not book or not name:
        return None
    guess = store.raw_dir(book) / (Path(name).stem + ".md")
    return guess if guess.is_file() else None


def learn_one(entry: dict, llm_complete=None) -> dict | None:
    """Classify one queued item and write ``entries/<id>.json``.

    Returns the learned entry, or ``None`` when the source is unreadable or the
    model answer cannot be parsed — in that case the item stays pending so a
    later pass retries it.
    """
    complete = llm_complete or llm.complete
    src = _raw_path(entry)
    if src is None:
        return None
    try:
        body = store.read_md(src)[1]
    except (OSError, ValueError):
        return None
    body = (body or "").strip()[:BODY_LIMIT]
    if not body:
        body = entry.get("file", "")
    try:
        raw = complete(CATALOG_SYSTEM, body)
    except Exception:
        return None
    d = _parse_json(raw or "")
    if d is None:
        return None

    domain = str(d.get("domain", "")).strip()
    if domain not in DOMAINS:
        domain = "기타"
    out = {
        **{k: entry.get(k) for k in ("id", "book", "file", "path", "sha256", "added_at")},
        "status": "learned",
        "learned_at": dt.datetime.now().isoformat(timespec="seconds"),
        "title": str(d.get("title") or entry.get("file") or "").strip(),
        "summary": str(d.get("summary") or "").strip(),
        "domain": domain,
        "tags": _str_list(d.get("tags"), 8),
        "concepts": _str_list(d.get("concepts"), 10),
        "entities": _str_list(d.get("entities"), 20),
        "links": _str_list(d.get("links"), 20),
    }
    entry_path(out["id"]).write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    return out


def learn_pending(limit: int = 10, llm_complete=None) -> dict:
    items = pending()[:max(0, limit)]
    ok = bad = 0
    for item in items:
        if learn_one(item, llm_complete=llm_complete) is None:
            bad += 1
        else:
            ok += 1
    return {"learned": ok, "failed": bad, "remaining": len(pending())}


# ---------------------------------------------------------------------------
# graph & stats
# ---------------------------------------------------------------------------

def graph() -> dict:
    """Concept co-occurrence graph across all learned entries."""
    counts: dict[str, int] = {}
    domains: dict[str, list[str]] = {}
    edges: dict[tuple[str, str], int] = {}
    for e in learned():
        concepts = [c for c in dict.fromkeys(e.get("concepts") or []) if c]
        domain = e.get("domain")
        for c in concepts:
            counts[c] = counts.get(c, 0) + 1
            bucket = domains.setdefault(c, [])
            if domain and domain not in bucket:
                bucket.append(domain)
        for a, b in itertools.combinations(sorted(concepts), 2):
            edges[(a, b)] = edges.get((a, b), 0) + 1
    g = {
        "nodes": [{"id": c, "count": n, "domains": sorted(domains.get(c, []))}
                  for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))],
        "edges": [{"a": a, "b": b, "w": w}
                  for (a, b), w in sorted(edges.items(), key=lambda kv: (-kv[1], kv[0]))],
    }
    graph_path().write_text(json.dumps(g, ensure_ascii=False, indent=1), "utf-8")
    return g


def stats() -> dict:
    q = _read_queue()
    done = learned()
    books = {i.get("book") for i in q if i.get("book")}
    books |= {e.get("book") for e in done if e.get("book")}
    concepts = {c for e in done for c in (e.get("concepts") or [])}
    learned_ids = {e.get("id") for e in done}
    return {
        "pending": sum(1 for i in q if i["id"] not in learned_ids),
        "learned": len(done),
        "books": len(books),
        "concepts": len(concepts),
    }


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------

def backfill() -> int:
    """Register every existing ``books/*/raw/*.md`` that is not catalogued yet."""
    root = get_settings().data_dir / "books"
    if not root.is_dir():
        return 0
    known = {i["id"] for i in _read_queue()} | {p.stem for p in entries_dir().glob("*.json")}
    n = 0
    for p in sorted(root.glob("*/raw/*.md")):
        slug = p.parts[-3]
        try:
            meta = store.read_md(p)[0]
        except (OSError, ValueError):
            meta = {}
        filename = str(meta.get("source") or p.name)
        sha = str(meta.get("sha256") or hashlib.sha256(p.read_bytes()).hexdigest())
        entry_id = make_id(slug, filename)
        if entry_id in known:
            continue
        register(slug, filename, p, sha)
        known.add(entry_id)
        n += 1
    return n
