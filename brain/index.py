import sqlite3
from contextlib import closing
from . import store
from .config import get_settings

def _db():
    con = sqlite3.connect(get_settings().data_dir / "brain.db")
    con.executescript("""
    CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(slug, path, body, tokenize='trigram');
    CREATE TABLE IF NOT EXISTS vec_meta(path TEXT PRIMARY KEY, model TEXT);""")
    return con

def rebuild() -> int:
    with closing(_db()) as con, con:
        con.execute("DELETE FROM docs")
        n = 0
        root = get_settings().data_dir / "books"
        for p in sorted(root.glob("*/raw/*.md")) + sorted(root.glob("*/notes/*.md")):
            slug = p.parts[-3]
            con.execute("INSERT INTO docs VALUES (?,?,?)", (slug, str(p.relative_to(root)), store.read_md(p)[1]))
            n += 1
    return n

def search(q: str, k: int = 10) -> list[dict]:
    match_q = '"' + q.replace('"', '""') + '"'
    with closing(_db()) as con:
        rows = con.execute("SELECT slug, path, snippet(docs, 2, '<mark>', '</mark>', '…', 12), bm25(docs) "
                           "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?", (match_q, k)).fetchall()
    return [{"slug": s, "path": p, "snippet": sn, "score": sc} for s, p, sn, sc in rows]
