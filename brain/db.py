"""The one place that opens ``brain.db`` (FTS index + knowledge-graph tables)."""
import sqlite3
import threading

from .config import get_settings

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(slug, path, body, tokenize='trigram');
CREATE TABLE IF NOT EXISTS vec_meta(path TEXT PRIMARY KEY, model TEXT);
CREATE TABLE IF NOT EXISTS nodes(
    id TEXT PRIMARY KEY, kind TEXT, label_ko TEXT, label_en TEXT, wikidata TEXT,
    field_code TEXT, summary TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS aliases(alias TEXT PRIMARY KEY, node_id TEXT);
CREATE TABLE IF NOT EXISTS node_tags(node_id TEXT, tag TEXT, PRIMARY KEY(node_id, tag));
CREATE TABLE IF NOT EXISTS edges(
    src TEXT, dst TEXT, rel TEXT, weight REAL, reason TEXT, evidence TEXT, created_at TEXT,
    PRIMARY KEY(src, dst, rel));
CREATE TABLE IF NOT EXISTS redirects(old_id TEXT PRIMARY KEY, new_id TEXT);
CREATE TABLE IF NOT EXISTS removed(id TEXT PRIMARY KEY);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_nodes_field ON nodes(field_code);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
"""

_ready: set[str] = set()  # db paths whose WAL mode + schema (+ vec tables) are set up this process
_ready_lock = threading.Lock()


def connect() -> sqlite3.Connection:
    """Open a fresh connection (caller closes it); the schema is created once per process per path."""
    path = get_settings().data_dir / "brain.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    fresh = not path.exists()  # deleted/new file: set it up again
    con = sqlite3.connect(path, timeout=30)
    from . import vec  # lazy: vec imports db
    with _ready_lock:
        if fresh:
            _ready.discard(key)
        if key not in _ready:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_SCHEMA)
            vec.ensure_tables(con)
            _ready.add(key)
            return con
    vec.load_extension(con)  # extensions are per connection; the DDL above is not
    return con
