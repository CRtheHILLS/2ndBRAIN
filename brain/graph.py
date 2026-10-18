"""Permanent knowledge graph.

Truth is the append-only event log ``<data_dir>/graph/events.jsonl``; the SQLite
tables are a cache that ``rebuild()`` can recreate by replaying the log through
the same ``_apply`` used by every live write.
"""
import datetime as dt
import json
import re
from collections import Counter
from contextlib import closing
from typing import Iterable

from . import db, frame
from .config import get_settings
from .slug import slugify

RELS = ("is_a", "part_of", "requires", "related", "bridge", "contradicts", "cites",
        "about", "in_book", "taught_in", "asked")
KINDS = ("concept", "source", "lesson", "quest", "book", "person", "place", "work", "question")

_NODE_COLS = ("id", "kind", "label_ko", "label_en", "wikidata", "field_code", "summary",
              "created_at", "updated_at")
_EDGE_COLS = ("src", "dst", "rel", "weight", "reason", "evidence", "created_at")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _norm(alias: str) -> str:
    return re.sub(r"\s+", " ", alias.strip()).lower()


def _log_path():
    p = get_settings().data_dir / "graph" / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append_event(ev: dict) -> dict:
    ev = {"t": _now(), **ev}
    with open(_log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def _apply(ev: dict, con) -> None:
    """Apply one event to the tables (shared by live writes and rebuild)."""
    op, t = ev["op"], ev["t"]
    if op == "node":
        row = con.execute("SELECT kind, label_ko, label_en, wikidata, field_code, summary "
                          "FROM nodes WHERE id=?", (ev["id"],)).fetchone()
        new = [ev.get(k, "") or "" for k in ("kind", "label_ko", "label_en", "wikidata",
                                             "field_code", "summary")]
        if row is None:
            con.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)", (ev["id"], *new, t, t))
        else:
            merged = [n or o for n, o in zip(new, row)]
            con.execute("UPDATE nodes SET kind=?, label_ko=?, label_en=?, wikidata=?, "
                        "field_code=?, summary=?, updated_at=? WHERE id=?", (*merged, t, ev["id"]))
    elif op == "alias":
        con.execute("INSERT OR REPLACE INTO aliases VALUES (?,?)", (_norm(ev["alias"]), ev["node_id"]))
    elif op == "tag":
        con.execute("INSERT OR IGNORE INTO node_tags VALUES (?,?)", (ev["node_id"], ev["tag"]))
    elif op == "edge":
        w = float(ev.get("weight", 1.0))
        row = con.execute("SELECT weight, created_at FROM edges WHERE src=? AND dst=? AND rel=?",
                          (ev["src"], ev["dst"], ev["rel"])).fetchone()
        created = row[1] if row else t
        if row and ev["rel"] == "related":
            w += row[0]
        con.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?,?,?)",
                    (ev["src"], ev["dst"], ev["rel"], w, ev.get("reason", ""),
                     ev.get("evidence", ""), created))
    elif op == "redirect":
        con.execute("INSERT OR REPLACE INTO redirects VALUES (?,?)", (ev["old_id"], ev["new_id"]))


def _write(*events: dict) -> None:
    """Log first, then apply the same events to the tables."""
    evs = [append_event(e) for e in events]
    with closing(db.connect()) as con, con:
        for ev in evs:
            _apply(ev, con)


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------

def upsert_node(id: str, kind: str, label_ko: str, label_en: str = "", wikidata: str = "",
                field_code: str = "", summary: str = "", tags: Iterable[str] = ()) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    evs = [{"op": "node", "id": id, "kind": kind, "label_ko": label_ko, "label_en": label_en,
            "wikidata": wikidata, "field_code": field_code, "summary": summary}]
    aliases = [label_ko, label_en] + ([f"wd:{wikidata}"] if wikidata else [])
    evs += [{"op": "alias", "alias": a, "node_id": id} for a in aliases if a and a.strip()]
    evs += [{"op": "tag", "node_id": id, "tag": t} for t in tags if t]
    _write(*evs)
    return get_node(id)


def add_alias(alias: str, node_id: str) -> None:
    _write({"op": "alias", "alias": alias, "node_id": node_id})


def add_edge(src: str, dst: str, rel: str, weight: float = 1.0, reason: str = "",
             evidence: str = "") -> None:
    if rel not in RELS:
        raise ValueError(f"unknown rel: {rel}")
    _write({"op": "edge", "src": resolve(src), "dst": resolve(dst), "rel": rel,
            "weight": weight, "reason": reason, "evidence": evidence})


def redirect(old_id: str, new_id: str) -> None:
    _write({"op": "redirect", "old_id": old_id, "new_id": new_id})


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def _node(con, id: str) -> dict | None:
    row = con.execute(f"SELECT {','.join(_NODE_COLS)} FROM nodes WHERE id=?", (id,)).fetchone()
    if row is None:
        return None
    d = dict(zip(_NODE_COLS, row))
    d["tags"] = [r[0] for r in con.execute(
        "SELECT tag FROM node_tags WHERE node_id=? ORDER BY tag", (id,))]
    return d


def _resolve(con, id: str) -> str:
    seen = {id}
    while (r := con.execute("SELECT new_id FROM redirects WHERE old_id=?", (id,)).fetchone()):
        id = r[0]
        if id in seen:
            break
        seen.add(id)
    return id


def resolve(id: str) -> str:
    with closing(db.connect()) as con:
        return _resolve(con, id)


def get_node(id: str) -> dict | None:
    with closing(db.connect()) as con:
        return _node(con, _resolve(con, id))


def find_alias(alias: str) -> str | None:
    with closing(db.connect()) as con:
        r = con.execute("SELECT node_id FROM aliases WHERE alias=?", (_norm(alias),)).fetchone()
        return _resolve(con, r[0]) if r else None


def search_labels(q: str, limit: int = 20) -> list[dict]:
    q = _norm(q)
    if not q:
        return []
    with closing(db.connect()) as con:
        rows = con.execute(
            "SELECT n.id, "
            "(lower(n.label_ko)=?1 OR lower(n.label_en)=?1 OR EXISTS "
            "  (SELECT 1 FROM aliases a WHERE a.node_id=n.id AND a.alias=?1)) AS exact, "
            "(SELECT count(*) FROM edges e WHERE e.src=n.id OR e.dst=n.id) AS deg "
            "FROM nodes n WHERE lower(n.label_ko) LIKE ?2 OR lower(n.label_en) LIKE ?2 "
            "OR EXISTS (SELECT 1 FROM aliases a WHERE a.node_id=n.id AND a.alias LIKE ?2) "
            "ORDER BY exact DESC, deg DESC, n.id LIMIT ?3", (q, f"%{q}%", limit)).fetchall()
        return [_node(con, r[0]) for r in rows]


def _edge_dicts(rows) -> list[dict]:
    return [dict(zip(_EDGE_COLS, r)) for r in rows]


def neighbors(id: str, depth: int = 1, rels: Iterable[str] | None = None) -> dict:
    depth = max(1, min(int(depth), 3))
    rel_set = set(rels) if rels else None
    with closing(db.connect()) as con:
        center = _resolve(con, id)
        seen, frontier = {center}, {center}
        edges: dict[tuple, dict] = {}
        for _ in range(depth):
            nxt: set[str] = set()
            for nid in frontier:
                rows = con.execute(f"SELECT {','.join(_EDGE_COLS)} FROM edges "
                                   "WHERE src=? OR dst=?", (nid, nid)).fetchall()
                for e in _edge_dicts(rows):
                    if rel_set and e["rel"] not in rel_set:
                        continue
                    edges[(e["src"], e["dst"], e["rel"])] = e
                    for end in (e["src"], e["dst"]):
                        if end not in seen:
                            seen.add(end)
                            nxt.add(end)
            frontier = nxt
        nodes = [n for n in (_node(con, i) for i in sorted(seen)) if n]
    return {"center": center, "nodes": nodes, "edges": list(edges.values())}


def _nodes_where(column: str, value: str, limit: int) -> list[dict]:
    with closing(db.connect()) as con:
        ids = [r[0] for r in con.execute(
            f"SELECT id FROM nodes WHERE {column}=? ORDER BY id LIMIT ?", (value, limit))]
        return [_node(con, i) for i in ids]


def by_field(code: str, limit: int = 200) -> list[dict]:
    return _nodes_where("field_code", code, limit)


def by_kind(kind: str, limit: int = 200) -> list[dict]:
    return _nodes_where("kind", kind, limit)


def full(limit: int = 2000) -> dict:
    with closing(db.connect()) as con:
        total = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
        ids = [r[0] for r in con.execute(
            "SELECT n.id FROM nodes n ORDER BY "
            "(SELECT count(*) FROM edges e WHERE e.src=n.id OR e.dst=n.id) DESC, n.id LIMIT ?",
            (limit,))]
        keep = set(ids)
        nodes = [_node(con, i) for i in ids]
        edges = [e for e in _edge_dicts(con.execute(
            f"SELECT {','.join(_EDGE_COLS)} FROM edges")) if e["src"] in keep and e["dst"] in keep]
    return {"nodes": nodes, "edges": edges, "truncated": total > len(ids)}


def stats() -> dict:
    with closing(db.connect()) as con:
        def one(sql: str) -> int:
            return con.execute(sql).fetchone()[0]
        areas = Counter(frame.area_of(c) for (c,) in con.execute(
            "SELECT field_code FROM nodes WHERE kind='concept' AND field_code!=''"))
        return {"nodes": one("SELECT count(*) FROM nodes"),
                "edges": one("SELECT count(*) FROM edges"),
                "concepts": one("SELECT count(*) FROM nodes WHERE kind='concept'"),
                "bridges": one("SELECT count(*) FROM edges WHERE rel='bridge'"),
                "by_area": dict(sorted(areas.items()))}


def node_ids_in_book(slug: str) -> list[str]:
    """Ids of the source nodes filed under a book."""
    with closing(db.connect()) as con:
        return [r[0] for r in con.execute(
            "SELECT src FROM edges WHERE dst=? AND rel='in_book' ORDER BY src", (f"book:{slug}",))]


def rebuild() -> int:
    """Wipe the graph tables and replay the event log; returns events replayed."""
    path = _log_path()
    n = 0
    with closing(db.connect()) as con, con:
        for t in ("nodes", "aliases", "node_tags", "edges", "redirects"):
            con.execute(f"DELETE FROM {t}")
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    _apply(json.loads(line), con)
                    n += 1
    return n


# ---------------------------------------------------------------------------
# catalog link
# ---------------------------------------------------------------------------

def _concept_id_fallback(label_ko: str, label_en: str = "") -> str:
    """Temporary concept id until canon.canon exists (Task 6)."""
    return slugify(label_en) or slugify(label_ko)


def ingest_card(entry: dict) -> list[str]:
    """Add one learned catalog entry to the graph; returns newly created concept ids."""
    code = frame.resolve_code(entry.get("field_code") or "")
    if not frame.is_valid_code(code):
        code = frame.FALLBACK_CODE
    src = "src:" + entry["id"][:16]
    book = entry.get("book") or ""
    upsert_node(src, "source", entry.get("title") or entry.get("file") or src,
                field_code=code, summary=entry.get("summary", ""), tags=entry.get("tags") or ())
    if book:
        upsert_node(f"book:{book}", "book", book)
        add_edge(src, f"book:{book}", "in_book")
    pairs = entry.get("concept_pairs") or [{"ko": c, "en": ""} for c in entry.get("concepts") or []]
    ids: list[str] = []
    new: list[str] = []
    for p in pairs:
        cid = _concept_id_fallback(p.get("ko", ""), p.get("en", ""))
        if not cid or cid in ids:
            continue
        if get_node(cid) is None:
            new.append(cid)
        upsert_node(cid, "concept", p.get("ko", ""), p.get("en", ""), field_code=code)
        add_edge(src, cid, "about")
        ids.append(cid)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            add_edge(*sorted((a, b)), "related", reason="co-occurs", evidence=src)
    return new
