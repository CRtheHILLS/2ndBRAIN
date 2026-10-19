"""Dot-to-dot bridges: link a concept to concepts learned at another time, in another book.

A standalone, re-runnable service (spec 5.8).  It is called from three places:
the quest ``bridge`` stage, the catalog learn hook (new concepts only) and the
manual ``POST /graph/rebridge``.  Candidates are cheap and generous; the thinker
decides which pairs GENUINELY connect, and only those become graph edges.
"""
import json
import logging
import re
import threading
from contextlib import closing

from pydantic import ValidationError

from . import db, frame, graph, models, prompts, quest, store, think

log = logging.getLogger(__name__)

BRIDGE_RELS = ("bridge", "requires", "is_a", "related")  # what the thinker may create
SHOWN_RELS = ("bridge", "requires", "is_a")  # what lesson pages list
MAX_PAIRS = 40
WHY_ORDER = ("alias", "wikidata_parent", "cooccur", "same_field", "vector")
WHY_KO = {"alias": "이름이 겹침", "wikidata_parent": "위키데이터에서 같은 상위 개념",
          "cooccur": "같은 자료에 함께 나온 개념과 이웃", "same_field": "같은 분야", "vector": "뜻이 비슷함"}
_LESSON = re.compile(r"^lesson:(.+):day-(\d+)$")
_SCAN = 200  # rows scanned per candidate source
_WIKIDATA_SCAN = 30  # other concepts whose Wikidata parents are looked up per node

_tls = threading.local()  # per-rebridge Wikidata parents cache


# ---------------------------------------------------------------------------
# membership
# ---------------------------------------------------------------------------

def _books(con, node_id: str) -> set[str]:
    """Book/quest slugs a node belongs to: via sources ``about`` it or lessons it is ``taught_in``."""
    group = sorted(graph._group(con, graph._resolve(con, node_id)))
    marks = ",".join("?" * len(group))
    holders = {r[0] for r in con.execute(
        f"SELECT src FROM edges WHERE rel='about' AND dst IN ({marks})", group)}
    holders |= {r[0] for r in con.execute(
        f"SELECT dst FROM edges WHERE rel='taught_in' AND src IN ({marks})", group)}
    out: set[str] = set()
    for h in holders:
        m = _LESSON.match(h)
        if m:
            out.add(m.group(1))
        for (b,) in con.execute("SELECT dst FROM edges WHERE rel='in_book' AND src=?", (h,)):
            if b.startswith("book:"):
                out.add(b[len("book:"):])
    return out


def books_of(node_id: str) -> set[str]:
    with closing(db.connect()) as con:
        return _books(con, node_id)


def _book_title(slug: str) -> str:
    try:
        q = json.loads((quest.quest_dir(slug) / "quest.json").read_text("utf-8"))
        title = (q.get("plan") or {}).get("title_ko") or q.get("title_ko")
        if title:
            return title
    except (OSError, ValueError):
        pass
    try:
        title = json.loads((store.book_dir(slug) / "book.json").read_text("utf-8")).get("title")
        if title:
            return title
    except (OSError, ValueError):
        pass
    return slug


def _label(node: dict | None, fallback: str) -> str:
    return (node or {}).get("label_ko") or (node or {}).get("label_en") or fallback


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------

def _parents(qid: str) -> list[str]:
    cache = getattr(_tls, "cache", None)
    if cache is None:
        cache = _tls.local_cache
    if qid not in cache:
        try:
            from .connectors import wikidata
            cache[qid] = list(wikidata.parents(qid))
        except Exception:  # noqa: BLE001 - network is optional
            cache[qid] = []
    return cache[qid]


def _alias_ids(con, node: dict) -> list[str]:
    out: list[str] = []
    for label in (node["label_ko"], node["label_en"]):
        lab = graph._norm(label or "")
        if len(lab) < (4 if lab.isascii() else 2):
            continue
        rows = con.execute(
            "SELECT n.id FROM nodes n WHERE n.kind='concept' AND n.id!=:me AND ("
            " (length(n.label_ko)>=2 AND (instr(lower(n.label_ko), :l)>0 OR instr(:l, lower(n.label_ko))>0))"
            " OR (length(n.label_en)>=4 AND (instr(lower(n.label_en), :l)>0 OR instr(:l, lower(n.label_en))>0)))"
            " ORDER BY n.updated_at DESC LIMIT :k", {"me": node["id"], "l": lab, "k": _SCAN}).fetchall()
        rows += con.execute(
            "SELECT node_id FROM aliases WHERE node_id!=:me AND alias NOT LIKE 'wd:%' AND "
            "(instr(alias, :l)>0 OR (length(alias)>=3 AND instr(:l, alias)>0)) LIMIT :k",
            {"me": node["id"], "l": lab, "k": _SCAN}).fetchall()
        out += [r[0] for r in rows]
    return out


def _wikidata_ids(con, node: dict, mine: set[str]) -> list[str]:
    qid = node.get("wikidata") or ""
    if not qid:
        return []
    ups = set(_parents(qid))
    out = [n for p in ups if (n := graph.find_alias(f"wd:{p}"))]  # a parent is itself learned
    rows = con.execute("SELECT id, wikidata FROM nodes WHERE kind='concept' AND wikidata!='' AND id!=? "
                       "ORDER BY updated_at DESC LIMIT ?", (node["id"], _SCAN)).fetchall()
    looked = 0
    for cid, cq in rows:
        if looked >= _WIKIDATA_SCAN:
            break
        books = _books(con, cid)
        if not books or books <= mine:
            continue
        looked += 1
        theirs = set(_parents(cq))
        if cq in ups or qid in theirs or ups & theirs:
            out.append(cid)
    return out


def _cooccur_ids(con, nid: str) -> list[str]:
    def related(ids):
        found = []
        for i in ids:
            for a, b in con.execute("SELECT src, dst FROM edges WHERE rel='related' AND (src=? OR dst=?)",
                                    (i, i)):
                found.append(b if a == i else a)
        return list(dict.fromkeys(found))
    first = related(sorted(graph._group(con, nid)))[:50]
    return first + related(first)


def _same_field_ids(con, node: dict) -> list[str]:
    code = node.get("field_code") or ""
    if not code or code == frame.FALLBACK_CODE:
        return []
    return [r[0] for r in con.execute(
        "SELECT id FROM nodes WHERE kind='concept' AND field_code=? AND id!=? "
        "ORDER BY updated_at DESC LIMIT ?", (code, node["id"], _SCAN))]


def _vector_ids(nid: str) -> list[str]:
    try:
        from . import vec  # a later task; optional
        hits = vec.similar_nodes(node_id=nid, k=5)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for h in hits or []:  # vec.similar_nodes returns (id, distance) tuples
        if isinstance(h, dict):
            out.append(h.get("id"))
        elif isinstance(h, (tuple, list)) and h:
            out.append(str(h[0]))
        else:
            out.append(str(h))
    return [i for i in out if i and i != nid]


def candidates(node_id: str, limit: int = 8) -> list[dict]:
    """Concepts from OTHER books/quests that might connect to ``node_id`` (the thinker decides)."""
    own_cache = getattr(_tls, "cache", None) is None
    if own_cache:
        _tls.local_cache = {}
    with closing(db.connect()) as con:
        nid = graph._resolve(con, node_id)
        node = graph._node(con, nid)
        if node is None:
            return []
        mine = _books(con, nid)
        sources = {"alias": lambda: _alias_ids(con, node),
                   "wikidata_parent": lambda: _wikidata_ids(con, node, mine),
                   "cooccur": lambda: _cooccur_ids(con, nid),
                   "same_field": lambda: _same_field_ids(con, node),
                   "vector": lambda: _vector_ids(nid)}
        out: list[dict] = []
        seen = {nid}
        for why in WHY_ORDER:
            for cid in sources[why]():
                cid = graph._resolve(con, cid or "")
                if cid in seen:
                    continue
                seen.add(cid)
                c = graph._node(con, cid)
                if not c or c["kind"] != "concept":
                    continue
                books = _books(con, cid)
                if not books or books <= mine:
                    continue
                out.append({"id": cid, "label_ko": c["label_ko"], "label_en": c["label_en"],
                            "field_code": c["field_code"], "why": why, "books": sorted(books)})
                if len(out) >= limit:
                    return out
        return out


def _linked(con, a: str, b: str) -> bool:
    return con.execute(
        "SELECT 1 FROM edges WHERE rel IN ('bridge','requires','is_a') AND "
        "((src=? AND dst=?) OR (src=? AND dst=?))", (a, b, b, a)).fetchone() is not None


def gather_pairs(node_ids: list[str], max_pairs: int = MAX_PAIRS) -> list[tuple[str, dict]]:
    """(src, candidate) pairs, round-robin over the nodes so one node cannot take every slot."""
    queues = [(graph.resolve(n), candidates(n)) for n in dict.fromkeys(node_ids)]
    pairs: list[tuple[str, dict]] = []
    taken: set[frozenset] = set()
    with closing(db.connect()) as con:
        for i in range(max((len(cs) for _, cs in queues), default=0)):
            for src, cs in queues:
                if len(pairs) >= max_pairs:
                    return pairs
                if i >= len(cs):
                    continue
                key = frozenset((src, cs[i]["id"]))
                if len(key) < 2 or key in taken or _linked(con, src, cs[i]["id"]):
                    continue
                taken.add(key)
                pairs.append((src, cs[i]))
    return pairs


# ---------------------------------------------------------------------------
# rebridge
# ---------------------------------------------------------------------------

def _describe(node: dict | None, nid: str, books) -> str:
    node = node or {}
    name = node.get("label_ko") or nid
    if node.get("label_en") and node.get("label_en") != name:
        name += f" ({node['label_en']})"
    code = node.get("field_code") or ""
    field = frame.fields().get(code, {}).get("name_ko") or code or "미분류"
    line = f"id={nid} 「{name}」 분야: {field} · 배운 곳: {', '.join(_book_title(b) for b in books) or '?'}"
    if node.get("summary"):
        line += f" — {node['summary'][:120]}"
    return line


def _user_message(pairs: list[tuple[str, dict]]) -> str:
    lines = [f"서로 다른 때 배운 개념 쌍 {len(pairs)}개. 쌍마다 정말 이어지는지 판정하라.", ""]
    for i, (src, c) in enumerate(pairs, 1):
        lines += [f"{i}. src: {_describe(graph.get_node(src), src, sorted(books_of(src)))}",
                  f"   dst: {_describe(graph.get_node(c['id']), c['id'], c['books'])}",
                  f"   후보가 된 까닭(참고만): {WHY_KO.get(c['why'], c['why'])}", ""]
    return "\n".join(lines).rstrip()


def rebridge(node_ids: list[str], *, complete=None, task_id: str | None = None,
             slug: str | None = None, strict: bool = False) -> list[dict]:
    """Ask the thinker about candidate pairs; store only confirmed links. Returns the new bridges.

    Inside a quest (``slug``) the think goes through ``quest.think_or_cached`` and ``Parked``
    propagates.  Outside, ``ThinkUnavailable`` is logged and swallowed unless ``strict``.
    """
    _tls.cache = {}
    try:
        pairs = gather_pairs(list(node_ids))
    finally:
        _tls.cache = None
    if not pairs:
        return []
    user = _user_message(pairs)
    try:
        if complete is not None:
            data = think.parse_json(complete(prompts.BRIDGE_SYSTEM, user) or "") or {}
        elif slug:
            data = quest.think_or_cached(slug, task_id or "bridge", "bridge", prompts.BRIDGE_SYSTEM,
                                         user, models.BridgeBatch)
        else:
            data = think.think("bridge", prompts.BRIDGE_SYSTEM, user, models.BridgeBatch).data
        batch = models.BridgeBatch.model_validate(data)
    except think.ThinkUnavailable as e:
        if slug or strict:
            raise
        log.warning("다리 판정을 건너뜀(생각 담당 없음): %s", "; ".join(e.reasons))
        return []
    except ValidationError as e:
        log.warning("다리 판정 답이 형식에 맞지 않아 버림: %s", e.errors()[:1])
        return []
    allowed = {(s, c["id"]) for s, c in pairs}
    made: list[dict] = []
    done: set[frozenset] = set()
    for v in batch.verdicts:
        key = frozenset((v.src, v.dst))  # one pair -> at most one edge, whatever the direction
        if not v.connects or v.rel not in BRIDGE_RELS or v.src == v.dst or key in done:
            continue
        if (v.src, v.dst) not in allowed and (v.dst, v.src) not in allowed:
            continue
        reason = v.reason.strip()
        if not reason:  # a link nobody can explain is not stored (honesty)
            log.info("이유 없는 다리 판정은 버림: %s ↔ %s", v.src, v.dst)
            continue
        graph.add_edge(v.src, v.dst, v.rel, weight=1.0, reason=reason, evidence="bridge")
        done.add(key)
        made.append({"src": v.src, "dst": v.dst, "rel": v.rel, "reason": reason})
    log.info("다리 %d개 생성 (쌍 %d개 판정)", len(made), len(pairs))
    return made


# ---------------------------------------------------------------------------
# reading & re-rendering
# ---------------------------------------------------------------------------

def bridges_for(node_ids: list[str]) -> list[dict]:
    """Shown links (bridge/requires/is_a) from these nodes to concepts of another book/quest."""
    prio = {r: i for i, r in enumerate(SHOWN_RELS)}
    out: dict[frozenset, dict] = {}  # one entry per pair, the highest-priority rel wins
    with closing(db.connect()) as con:
        ids = {graph._resolve(con, n) for n in node_ids}
        books: dict[str, set[str]] = {}

        def books_cached(n):
            if n not in books:
                books[n] = _books(con, n)
            return books[n]
        for me in sorted(ids):
            group = sorted(graph._group(con, me))
            marks = ",".join("?" * len(group))
            rows = con.execute(
                f"SELECT src, dst, rel, reason FROM edges WHERE rel IN ('bridge','requires','is_a') "
                f"AND (src IN ({marks}) OR dst IN ({marks}))", group + group).fetchall()
            for s, d, rel, reason in rows:
                s, d = graph._resolve(con, s), graph._resolve(con, d)
                other = d if s == me else s
                if other == me:
                    continue
                key = frozenset((me, other))
                if key in out and prio[out[key]["rel"]] <= prio[rel]:
                    continue
                theirs = books_cached(other) - books_cached(me)
                if not theirs:
                    continue
                out[key] = {"src": me, "dst": other, "rel": rel, "reason": reason or "",
                            "src_label": _label(graph._node(con, me), me),
                            "dst_label": _label(graph._node(con, other), other),
                            "dst_books": [_book_title(b) for b in sorted(theirs)]}
    return sorted(out.values(), key=lambda b: (prio[b["rel"]], b["src_label"], b["dst_label"]))


def _lesson_days(node_ids) -> dict[str, set[int]]:
    days: dict[str, set[int]] = {}
    with closing(db.connect()) as con:
        for n in node_ids:
            group = sorted(graph._group(con, graph._resolve(con, n)))
            marks = ",".join("?" * len(group))
            for (lid,) in con.execute(f"SELECT dst FROM edges WHERE rel='taught_in' AND src IN ({marks})",
                                      group):
                m = _LESSON.match(lid)
                if m:
                    days.setdefault(m.group(1), set()).add(int(m.group(2)))
    return days


def affected_quests(node_ids) -> list[str]:
    """Quest slugs whose lessons teach any of these concepts."""
    return sorted(_lesson_days(node_ids))


def rerender_affected(node_ids) -> list[str]:
    """Re-render the affected day pages and each quest's map page (no thinking)."""
    from . import render
    days = _lesson_days(node_ids)
    for slug in sorted(days):
        for n in sorted(days[slug]):
            try:
                render.render_quest_day(slug, n)
            except Exception as e:  # noqa: BLE001 - one broken page must not stop the rest
                log.warning("다시 그리기 실패 %s day-%d: %s", slug, n, e)
        try:
            render.render_quest(slug)
        except Exception as e:  # noqa: BLE001
            log.warning("다시 그리기 실패 %s 지도: %s", slug, e)
    return sorted(days)


def recent_concepts(limit: int = 50) -> list[str]:
    with closing(db.connect()) as con:
        return [r[0] for r in con.execute(
            "SELECT id FROM nodes WHERE kind='concept' ORDER BY updated_at DESC, id LIMIT ?", (limit,))]
