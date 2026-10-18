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
import logging
from pathlib import Path

from pydantic import ValidationError

from . import frame, models, prompts, store, think
from . import graph as knowledge_graph
from .config import get_settings
from .think import parse_json

log = logging.getLogger(__name__)

DOMAINS = ["과학", "역사", "종교", "철학", "심리", "경제", "기술", "예술", "동물", "건강", "기타"]

BODY_LIMIT = 15000


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

_parse_json = parse_json  # salvage logic lives in think.py


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


def _complete_default(system: str, user: str) -> str:
    return think.complete_text(system, user, smart=False)[0]


def _cards_from(d: dict, first_index: int) -> dict[int, models.CatalogCard]:
    """Validate a parsed answer into ``{index: card}``; bad cards are skipped."""
    raw = d.get("cards")
    single = not isinstance(raw, list)
    if single:
        raw = [d] if "title" in d else []
    out: dict[int, models.CatalogCard] = {}
    for c in raw:
        if not isinstance(c, dict):
            continue
        if single and "index" not in c:
            c = {**c, "index": first_index}
        try:
            card = models.CatalogCard.model_validate(c)
        except ValidationError:
            continue
        out.setdefault(card.index, card)
    return out


def learn_batch(entries: list[dict], complete=None) -> list[dict | None]:
    """Classify several queued items in one model call.

    Returns one learned entry (or ``None``) per input entry, in order.  A
    ``None`` means unreadable source, missing/invalid card, or a failed call:
    the item stays pending.  ``think.ThinkUnavailable`` propagates.
    """
    complete = complete or _complete_default
    results: list[dict | None] = [None] * len(entries)
    if not entries:
        return results
    budget = BODY_LIMIT // len(entries)
    blocks, sent = [], []
    for pos, entry in enumerate(entries):
        src = _raw_path(entry)
        if src is None:
            continue
        try:
            body = store.read_md(src)[1]
        except (OSError, ValueError):
            continue
        body = (body or "").strip()[:budget] or entry.get("file", "")
        blocks.append(f"### 자료 {pos + 1}\n제목 힌트: {entry.get('file', '')}\n\n{body}")
        sent.append(pos)
    if not sent:
        return results
    try:
        raw = complete(prompts.catalog_batch_system(), "\n\n".join(blocks))
    except think.ThinkUnavailable:
        raise
    except Exception:
        return results
    d = _parse_json(raw or "")
    if d is None:
        return results
    cards = _cards_from(d, sent[0] + 1)
    for pos in sent:
        card = cards.get(pos + 1)
        if card is None:
            continue
        entry = entries[pos]
        domain = card.domain.strip()
        if domain not in DOMAINS:
            domain = "기타"
        code = card.field_code.strip()
        code = frame.resolve_code(code) if frame.is_valid_code(code) else frame.FALLBACK_CODE
        pairs = [{"ko": p.ko.strip(), "en": p.en.strip()} for p in card.concept_pairs if p.ko.strip()]
        concepts = _str_list(card.concepts, 10) or _str_list([p["ko"] for p in pairs], 10)
        out = {
            **{k: entry.get(k) for k in ("id", "book", "file", "path", "sha256", "added_at")},
            "status": "learned",
            "learned_at": dt.datetime.now().isoformat(timespec="seconds"),
            "title": card.title.strip() or str(entry.get("file") or ""),
            "summary": card.summary.strip(),
            "domain": domain,
            "field_code": code,
            "tags": _str_list(card.tags, 8),
            "concepts": concepts,
            "concept_pairs": pairs,
            "entities": _str_list(card.entities, 20),
            "links": [],
        }
        entry_path(out["id"]).write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
        results[pos] = out
    return results


def learn_one(entry: dict, llm_complete=None) -> dict | None:
    """Classify a single queued item (a batch of one)."""
    return learn_batch([entry], complete=llm_complete)[0]


def _after_learn(entries: list[dict]) -> list[str]:
    """Put freshly learned entries into the graph; returns new concept ids."""
    out: list[str] = []
    to_bridge: list[str] = []
    for e in entries:
        new = [c for c in knowledge_graph.ingest_card(e) if c not in out]
        out.extend(new)
        if not _is_quest_book(e.get("book") or ""):  # a quest bridges its own concepts in its stage
            to_bridge.extend(new)
    if to_bridge:
        try:
            from . import bridge
            made = bridge.rebridge(to_bridge)
            if made:
                bridge.rerender_affected(list(dict.fromkeys(x for b in made for x in (b["src"], b["dst"]))))
        except Exception as e:  # noqa: BLE001 - bridging must never break /catalog/learn
            log.warning("새 개념 다리 놓기 실패(학습은 저장됨): %s", e)
    return out


def _is_quest_book(book: str) -> bool:
    if not book:
        return False
    from . import quest
    return (quest.quest_dir(book) / "quest.json").is_file()


def learn_pending(limit: int = 10, llm_complete=None, book: str | None = None,
                  batch_size: int = 5) -> dict:
    def todo() -> list[dict]:
        return [i for i in pending() if book is None or i.get("book") == book]

    items = todo()[:max(0, limit)]
    size = max(1, batch_size)
    learned = bad = 0
    new_concepts: list[str] = []
    for i in range(0, len(items), size):
        batch_done = []
        for r in learn_batch(items[i:i + size], complete=llm_complete):
            if r is None:
                bad += 1
            else:
                batch_done.append(r)
        # graph upsert right after each batch so a later ThinkUnavailable loses nothing
        learned += len(batch_done)
        new_concepts += [c for c in _after_learn(batch_done) if c not in new_concepts]
    return {"learned": learned, "failed": bad, "remaining": len(todo()),
            "new_concepts": new_concepts}


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
