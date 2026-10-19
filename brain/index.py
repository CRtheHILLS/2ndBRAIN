"""Full-text index over the volume: raw/notes Markdown under ``books/`` and quest lessons under ``quests/``."""
import json
import logging
import re
from contextlib import closing
from pathlib import Path

from . import db, store, textutil
from .config import get_settings

log = logging.getLogger(__name__)

_LESSON_PATH = re.compile(r"^([^/\\]+)[/\\]days[/\\]day-(\d+)\.json$")


def lesson_text(lesson: dict) -> str:
    """Searchable body of a DayLesson: big idea, story, every dot's explanation, quiz q/a."""
    parts = [lesson.get("big_idea_one_line") or "", lesson.get("story_opening") or ""]
    for d in lesson.get("dots") or []:
        parts.append(d.get("concept_ko") or "")
        for key in ("one_line", "analogy", "real_example", "why_it_matters"):
            parts.append(d.get(key) or "")
    for qi in lesson.get("quiz") or []:
        parts += [qi.get("q") or "", qi.get("a") or ""]
    return "\n".join(p for p in parts if p.strip())


def is_lesson_path(path: str) -> bool:
    return bool(_LESSON_PATH.match(path or ""))


def read_doc(path: str) -> tuple[str, str] | None:
    """(title, body) of an indexed doc path, or None when the file is gone/unreadable.

    ``<book>/raw|notes/<x>.md`` lives under ``books/``; ``<quest>/days/day-N.json`` under ``quests/``.
    """
    data_dir = get_settings().data_dir
    m = _LESSON_PATH.match(path or "")
    try:
        if m:
            p = data_dir / "quests" / m.group(1) / "days" / f"day-{m.group(2)}.json"
            if not p.is_file():
                return None
            lesson = json.loads(p.read_text("utf-8"))
            title = f"{m.group(1)} · {m.group(2)}일차 수업"
            return title, lesson_text(lesson)
        p = data_dir / "books" / path
        if not p.is_file():
            return None
        meta, body = store.read_md(p)
        return str(meta.get("title") or meta.get("source") or Path(path).stem), body
    except (OSError, ValueError) as e:
        log.warning("read_doc %s failed: %s", path, e)
        return None


def lesson_docs() -> list[tuple[str, str, str]]:
    """(quest slug, index path, body) for every valid lesson JSON under ``quests/``."""
    out = []
    for p in sorted((get_settings().data_dir / "quests").glob("*/days/day-*.json")):
        try:
            lesson = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(lesson, dict):
            continue
        slug = p.parts[-3]
        n = p.stem.split("-", 1)[1]
        out.append((slug, f"{slug}/days/day-{n}.json", lesson_text(lesson)))
    return out


def rebuild() -> int:
    with closing(db.connect()) as con, con:
        con.execute("DELETE FROM docs")
        n = 0
        root = get_settings().data_dir / "books"
        for p in sorted(root.glob("*/raw/*.md")) + sorted(root.glob("*/notes/*.md")):
            slug = p.parts[-3]
            con.execute("INSERT INTO docs VALUES (?,?,?)", (slug, str(p.relative_to(root)), store.read_md(p)[1]))
            n += 1
        for slug, path, body in lesson_docs():
            con.execute("INSERT INTO docs VALUES (?,?,?)", (slug, path, body))
            n += 1
    return n


def _fts(con, terms: list[str], op: str, likes: list[str], k: int) -> list[tuple]:
    """FTS5 (trigram) over ``terms`` joined by ``op``; ``likes`` (2-char words) must also be in the body."""
    match_q = f" {op} ".join('"' + t.replace('"', '""') + '"' for t in terms)
    sql = ("SELECT slug, path, snippet(docs, 2, '<mark>', '</mark>', '…', 12), bm25(docs) "
           "FROM docs WHERE docs MATCH ?" + "".join(" AND body LIKE ?" for _ in likes) +
           " ORDER BY bm25(docs) LIMIT ?")
    return con.execute(sql, (match_q, *[f"%{t}%" for t in likes], k)).fetchall()


def _like(con, words: list[str], op: str, k: int) -> list[tuple]:
    """Plain LIKE scan for words the trigram tokenizer cannot match (< 3 chars)."""
    where = f" {op} ".join("body LIKE ?" for _ in words)
    return con.execute(f"SELECT slug, path, substr(body, max(1, instr(body, ?) - 60), 200), 0 "
                       f"FROM docs WHERE {where} LIMIT ?", (words[0], *[f"%{w}%" for w in words], k)).fetchall()


def search(q: str, k: int = 10) -> list[dict]:
    """Tokenized search: AND over all words first; if nothing matches, OR over them.

    Words of >= 3 chars go through FTS5 (trigram needs 3); 2-char words use ``LIKE`` on the body
    and the two result sets are unioned.  Result shape: ``{slug, path, snippet, score}``.
    """
    toks = textutil.tokens(q)
    long_terms = [t for t in toks if len(t) >= 3]
    short = [t for t in toks if len(t) == 2]
    with closing(db.connect()) as con:
        if not toks:
            raw = (q or "").strip()
            if not raw:
                return []
            rows = con.execute("SELECT slug, path, substr(body,1,200), 0 FROM docs WHERE body LIKE ? LIMIT ?",
                               (f"%{raw}%", k)).fetchall()
        elif long_terms:
            rows = _fts(con, long_terms, "AND", short, k)
            if not rows:
                rows = _fts(con, long_terms, "OR", [], k) + (_like(con, short, "OR", k) if short else [])
        else:
            rows = _like(con, short, "AND", k) or _like(con, short, "OR", k)
    out, seen = [], set()
    for s, p, sn, sc in rows:
        if p in seen:
            continue
        seen.add(p)
        out.append({"slug": s, "path": p, "snippet": sn, "score": sc})
    return out[:k]
