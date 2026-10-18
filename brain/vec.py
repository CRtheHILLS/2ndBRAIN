"""sqlite-vec index over graph nodes and book chunks. Silent no-op without the extension or embeddings."""
import logging
import struct
from contextlib import closing

from . import db, embed
from .config import get_settings

log = logging.getLogger(__name__)
AVAILABLE = True

_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS node_vec USING vec0(node_id TEXT PRIMARY KEY, embedding float[768])",
    "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(chunk_id TEXT PRIMARY KEY, embedding float[768])",
    "CREATE TABLE IF NOT EXISTS chunk_text(chunk_id TEXT PRIMARY KEY, slug TEXT, path TEXT, start INTEGER, text TEXT)",
)


def ensure_tables(con) -> bool:
    """Load sqlite-vec and create the vec tables; sets ``AVAILABLE``."""
    global AVAILABLE
    try:
        import sqlite_vec
        con.enable_load_extension(True)
        try:
            sqlite_vec.load(con)
        finally:
            con.enable_load_extension(False)
        for ddl in _DDL:
            con.execute(ddl)
        AVAILABLE = True
    except Exception as e:
        AVAILABLE = False
        log.debug("sqlite-vec unavailable: %s", e)
    return AVAILABLE


def _blob(v: list[float]) -> bytes:
    import sqlite_vec
    return sqlite_vec.serialize_float32(v)


def _open():
    """A connection with vec loaded, or None when sqlite-vec is unavailable."""
    con = db.connect()
    if AVAILABLE:
        return con
    con.close()
    return None


def _node_text(n: dict) -> str:
    return f"{n.get('label_ko') or ''} {n.get('label_en') or ''} {(n.get('summary') or '')[:300]}".strip()


def index_nodes(node_ids: list[str]) -> int:
    try:
        from . import graph
        nodes = [n for n in (graph.get_node(i) for i in node_ids) if n]
        if not nodes:
            return 0
        con = _open()
        if con is None:
            return 0
        with closing(con):
            vecs = embed.embed([_node_text(n) for n in nodes])
            if vecs is None:
                return 0
            with con:
                for n, v in zip(nodes, vecs):
                    con.execute("DELETE FROM node_vec WHERE node_id=?", (n["id"],))
                    con.execute("INSERT INTO node_vec(node_id, embedding) VALUES (?,?)", (n["id"], _blob(v)))
        return len(nodes)
    except Exception as e:
        log.warning("index_nodes failed: %s", e)
        return 0


def _chunks(text: str, size: int) -> list[tuple[int, str]]:
    return [(i, text[i:i + size]) for i in range(0, len(text), size) if text[i:i + size].strip()]


def index_doc(slug: str, path: str, text: str, chunk_chars: int = 800) -> int:
    try:
        con = _open()
        if con is None:
            return 0
        with closing(con):
            have = dict(con.execute("SELECT chunk_id, text FROM chunk_text WHERE slug=? AND path=?", (slug, path)))
            # new chunks, plus chunks whose text changed since they were embedded
            todo = [(s, t) for s, t in _chunks(text, chunk_chars) if have.get(f"{slug}/{path}#{s}") != t]
            if not todo:
                return 0
            vecs = embed.embed([t for _, t in todo])
            if vecs is None:
                return 0
            with con:
                for (s, t), v in zip(todo, vecs):
                    cid = f"{slug}/{path}#{s}"
                    con.execute("DELETE FROM chunk_vec WHERE chunk_id=?", (cid,))
                    con.execute("INSERT INTO chunk_vec(chunk_id, embedding) VALUES (?,?)", (cid, _blob(v)))
                    con.execute("INSERT OR REPLACE INTO chunk_text VALUES (?,?,?,?,?)", (cid, slug, path, s, t))
            return len(todo)
    except Exception as e:
        log.warning("index_doc failed: %s", e)
        return 0


def delete_book(slug: str) -> int:
    """Drop a book's chunk rows (node vectors stay: concepts outlive books)."""
    try:
        con = _open()
        if con is None:
            return 0
        with closing(con), con:
            ids = [r[0] for r in con.execute("SELECT chunk_id FROM chunk_text WHERE slug=?", (slug,))]
            for cid in ids:
                con.execute("DELETE FROM chunk_vec WHERE chunk_id=?", (cid,))
            con.execute("DELETE FROM chunk_text WHERE slug=?", (slug,))
        return len(ids)
    except Exception as e:
        log.warning("delete_book failed: %s", e)
        return 0


def index_book(slug: str) -> int:
    try:
        from . import store
        root = get_settings().data_dir / "books"
        n = 0
        for p in sorted((root / slug / "raw").glob("*.md")):
            n += index_doc(slug, p.relative_to(root).as_posix(), store.read_md(p)[1])
        return n
    except Exception as e:
        log.warning("index_book failed: %s", e)
        return 0


def _knn(con, table: str, col: str, vec: list[float], k: int):
    return con.execute(f"SELECT {col}, distance FROM {table} WHERE embedding MATCH ? "
                       f"ORDER BY distance LIMIT ?", (_blob(vec), k)).fetchall()


def similar_nodes(text: str | None = None, node_id: str | None = None, k: int = 5) -> list[tuple[str, float]]:
    try:
        con = _open()
        if con is None:
            return []
        with closing(con):
            vec = None
            if node_id:
                row = con.execute("SELECT embedding FROM node_vec WHERE node_id=?", (node_id,)).fetchone()
                if row:
                    vec = list(struct.unpack(f"{len(row[0]) // 4}f", row[0]))
                else:
                    from . import graph
                    n = graph.get_node(node_id)
                    text = _node_text(n) if n else None
            if vec is None:
                if not text:
                    return []
                got = embed.embed([text], task="query")
                if not got:
                    return []
                vec = got[0]
            rows = _knn(con, "node_vec", "node_id", vec, k + 1)
        return [(i, float(d)) for i, d in rows if i != node_id][:k]
    except Exception as e:
        log.warning("similar_nodes failed: %s", e)
        return []


def similar_chunks(text: str, k: int = 8) -> list[dict]:
    try:
        if not text:
            return []
        con = _open()
        if con is None:
            return []
        with closing(con):
            got = embed.embed([text], task="query")
            if not got:
                return []
            out = []
            for cid, dist in _knn(con, "chunk_vec", "chunk_id", got[0], k):
                m = con.execute("SELECT slug, path, start, text FROM chunk_text WHERE chunk_id=?", (cid,)).fetchone()
                if m:
                    out.append({"chunk_id": cid, "slug": m[0], "path": m[1], "start": m[2],
                                "text": m[3], "distance": float(dist)})
            return out
    except Exception as e:
        log.warning("similar_chunks failed: %s", e)
        return []
