"""Obsidian vault export: the whole knowledge graph as a zip of linked Markdown files."""
import io
import json
import re
import zipfile
from contextlib import closing

from . import catalog, db, frame, graph, quest, store

README = """# 2nd BRAIN 볼트

이 폴더는 클레어와 함께 쌓은 지식 그래프를 Obsidian에서 바로 열 수 있게 내보낸 것이에요.

## 여는 법
1. 압축을 풀어요.
2. Obsidian을 켜고 "보관함 폴더 열기"로 `vault` 폴더를 골라요.
3. 왼쪽의 그래프 보기를 누르면 점과 선으로 이어진 지식 지도가 보여요.

## 폴더 구성
- `<영역>/<분야>/` : 개념 하나가 파일 하나예요. 어느 분야에도 못 넣은 개념은 `미분류/`에 있어요.
- `퀘스트/` : 배운 퀘스트와 하루치 수업이에요.
- `자료/` : 개념을 뒷받침하는 자료(책·문서)예요.
- `서재/` : 책 한 권마다 담긴 자료와 개념 목록이에요.

## 링크는 이렇게 이어져요
- `[[개념 이름]]` 을 누르면 그 개념 파일로 가요. 이름이 겹치는 개념은 이름 뒤에 분야 코드가 붙어요.
- 개념 파일의 "이어진 개념"은 다리(bridge), 먼저 알아야 할 것(requires), 위 개념(is_a), 관련 개념(related)이에요.
- "수업"에는 그 개념을 배운 날의 수업 링크가 있어요.
- 맨 위 `tags`와 `aliases`로 영역·분야·다른 이름을 찾아볼 수 있어요.

이 볼트는 서버에서 만든 사본이에요. 여기서 고쳐도 서버에는 반영되지 않아요.
"""

_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]')
SHOWN_RELS = ("bridge", "requires", "is_a", "related")


def _clean(name: str) -> str:
    s = _BAD.sub(" ", name or "").strip(" .")
    s = re.sub(r"\s+", " ", s)[:80].strip(" .")
    if re.fullmatch(r"(?i)con|prn|aux|nul|com[1-9]|lpt[1-9]", s.split(".")[0]):
        s += "_"
    return s or "이름없음"


def _yaml(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)


def _rows(con, sql: str, args=()) -> list[dict]:
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _read_days(slug: str) -> list[dict]:
    out = []
    for p in sorted((quest.quest_dir(slug) / "days").glob("day-*.json")):
        try:
            d = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(d, dict) and isinstance(d.get("n"), int):
            out.append(d)
    return sorted(out, key=lambda d: d["n"])


def build_zip() -> bytes:
    fields = frame.fields()
    area_name = {a["code"]: a["name_ko"] for a in frame.load()["areas"]}
    files: dict[str, str] = {"vault/README.md": README}

    with closing(db.connect()) as con:
        nodes = _rows(con, "SELECT * FROM nodes ORDER BY id")
        tags: dict[str, list[str]] = {}
        for nid, tag in con.execute("SELECT node_id, tag FROM node_tags ORDER BY tag"):
            tags.setdefault(nid, []).append(tag)
        aliases: dict[str, list[str]] = {}
        for al, nid in con.execute("SELECT alias, node_id FROM aliases ORDER BY alias"):
            aliases.setdefault(nid, []).append(al)
        edges = _rows(con, "SELECT * FROM edges ORDER BY src, dst, rel")

    by_id = {n["id"]: n for n in nodes}
    concepts = [n for n in nodes if n["kind"] == "concept"]

    # ---- concept paths / stems -------------------------------------------------
    def folder(n: dict) -> str:
        f = fields.get(n["field_code"] or "")
        if not f:
            return "미분류"
        return f"{_clean(area_name.get(f['area'], f['area']))}/{_clean(f['name_ko'])}"

    stem: dict[str, str] = {}
    used: set[str] = {"readme"}  # basenames are global: Obsidian resolves [[stem]] vault-wide

    def unique(base: str, suffix: str = "") -> str:
        s = base
        if s.lower() in used and suffix:
            s = _clean(f"{base}-{suffix}")
        k = 2
        while s.lower() in used:
            s = f"{base}-{suffix}-{k}" if suffix else f"{base}-{k}"
            k += 1
        used.add(s.lower())
        return s

    for n in concepts:
        stem[n["id"]] = unique(_clean(n["label_ko"] or n["label_en"] or n["id"]), n["field_code"] or "x")
    source_stem = {n["id"]: unique(_clean(n["id"].replace(":", "-"))) for n in nodes if n["kind"] == "source"}
    book_slugs = {e["dst"][5:] for e in edges if e["rel"] == "in_book" and e["dst"].startswith("book:")}
    book_slugs |= {b.get("slug") for b in store.list_books() if b.get("slug")}
    book_stem = {slug: unique(_clean(slug)) for slug in sorted(book_slugs)}
    path_of = {n["id"]: f"vault/{folder(n)}/{stem[n['id']]}.md" for n in concepts}

    def link(cid: str) -> str:
        return f"[[{stem[cid]}]]"

    # ---- quests / lessons ------------------------------------------------------
    lessons_of: dict[str, list[tuple[str, int]]] = {}
    quests = quest.list_quests()
    quest_days: dict[str, list[dict]] = {}
    for q in quests:
        slug = q.get("slug")
        if not slug:
            continue
        days = _read_days(slug)
        quest_days[slug] = days
        for d in days:
            for dot in d.get("dots", []):
                cid = graph.resolve(dot["concept_id"]) if dot.get("concept_id") else ""
                if cid in stem and (slug, d["n"]) not in lessons_of.get(cid, []):
                    lessons_of.setdefault(cid, []).append((slug, d["n"]))

    # ---- sources -----------------------------------------------------------------
    entries = {e["id"][:16]: e for e in catalog.learned() if e.get("id")}

    def src_stem(nid: str) -> str:
        return source_stem[nid]

    about: dict[str, list[str]] = {}
    for e in edges:
        if e["rel"] == "about" and e["dst"] in stem and by_id.get(e["src"], {}).get("kind") == "source":
            about.setdefault(e["src"], []).append(e["dst"])
    sources_of: dict[str, list[str]] = {}
    for sid, cids in about.items():
        for c in cids:
            sources_of.setdefault(c, []).append(sid)

    def src_url(nid: str) -> str:
        e = entries.get(nid.split(":", 1)[-1])
        if not e:
            return ""
        try:
            raw = catalog._raw_path(e) if (e.get("path") or e.get("book")) else None
            src = str(store.read_md(raw)[0].get("source") or "").strip() if raw else ""
        except (OSError, ValueError, KeyError):
            return ""
        return src if src.startswith("http") else ""

    # ---- concept files -----------------------------------------------------------
    out_edges: dict[str, list[dict]] = {}
    for e in edges:
        if e["rel"] in SHOWN_RELS and e["src"] in stem and e["dst"] in stem:
            if e["rel"] == "related" and (e["weight"] or 0) < 2:
                continue
            out_edges.setdefault(e["src"], []).append({**e, "other": e["dst"]})
            out_edges.setdefault(e["dst"], []).append({**e, "other": e["src"]})

    for n in concepts:
        cid = n["id"]
        f = fields.get(n["field_code"] or "")
        tg = ([area_name.get(f["area"], f["area"]), f["name_ko"]] if f else []) + tags.get(cid, [])
        al = [a for a in aliases.get(cid, []) if not a.startswith("wd:")]
        lines = ["---", f"id: {_yaml(cid)}", f"kind: {n['kind']}",
                 "tags: [" + ", ".join(_yaml(t) for t in dict.fromkeys(tg)) + "]",
                 f"wikidata: {_yaml(n['wikidata'] or '')}",
                 "aliases: [" + ", ".join(_yaml(a) for a in al) + "]",
                 f"field_code: {_yaml(n['field_code'] or '')}", "---", ""]
        title = n["label_ko"] + (f" ({n['label_en']})" if n["label_en"] else "")
        lines += [f"# {title}", "", n["summary"] or "", ""]
        rel_lines, seen = [], set()
        for e in out_edges.get(cid, []):
            key = (e["other"], e["rel"])
            if key in seen:
                continue
            seen.add(key)
            rel = e["rel"] if e["src"] == cid else f"{e['rel']}(역)"
            rel_lines.append(f"- {link(e['other'])} — {rel}" + (f" — {e['reason']}" if e["reason"] else ""))
        if rel_lines:
            lines += ["## 이어진 개념", *rel_lines, ""]
        srcs = sources_of.get(cid, [])
        if srcs:
            lines.append("## 자료")
            for sid in srcs:
                u = src_url(sid)
                lines.append(f"- [[{src_stem(sid)}]]" + (f" — {u}" if u else ""))
            lines.append("")
        if lessons_of.get(cid):
            lines.append("## 수업")
            lines += [f"- [[퀘스트/{s}/day-{d}]]" for s, d in lessons_of[cid]]
            lines.append("")
        files[path_of[cid]] = "\n".join(lines).rstrip() + "\n"

    # ---- quest files -------------------------------------------------------------
    for q in quests:
        slug = q.get("slug")
        if not slug:
            continue
        plan = q.get("plan") or {}
        h = plan.get("honesty") or {}
        days = quest_days.get(slug, [])
        r = [f"# {plan.get('title_ko') or q.get('sentence', slug)}", "",
             f"- 처음 한 문장: {q.get('sentence', '')}", f"- 눈높이: {q.get('level', '')}",
             f"- 목표: {plan.get('one_line_goal', '')}", ""]
        for key, head in (("learnable_by_reading", "읽어서 배울 수 있는 것"),
                          ("needs_practice", "직접 해 봐야 하는 것"), ("hype_warning", "과장 주의")):
            if h.get(key):
                r += [f"## {head}", *[f"- {x}" for x in h[key]], ""]
        r += ["## 하루별 수업", *[f"- [[퀘스트/{slug}/day-{d['n']}]] — {d.get('big_idea_one_line', '')}"
                              for d in days], ""]
        files[f"vault/퀘스트/{_clean(slug)}/README.md"] = "\n".join(r).rstrip() + "\n"
        for d in days:
            t = [f"# {slug} · {d['n']}일차", "", f"**큰 생각:** {d.get('big_idea_one_line', '')}", ""]
            if d.get("story_opening"):
                t += [d["story_opening"], ""]
            for dot in d.get("dots", []):
                t += [f"### {dot.get('concept_ko', '')}", dot.get("one_line", ""), ""]
                for key, lab in (("analogy", "비유"), ("real_example", "실제 예"),
                                 ("why_it_matters", "왜 중요한가")):
                    if dot.get(key):
                        t.append(f"- {lab}: {dot[key]}")
                t.append(f"- 증거 등급: {dot.get('evidence_grade', '')}")
                cid = graph.resolve(dot["concept_id"]) if dot.get("concept_id") else ""
                if cid in stem:
                    t.append(f"- 개념: {link(cid)}")
                for u in dot.get("sources", []):
                    t.append(f"- 출처: {u}")
                t.append("")
            if d.get("quiz"):
                t.append("## 퀴즈")
                for i, qi in enumerate(d["quiz"], 1):
                    t += [f"{i}. Q. {qi.get('q', '')}", f"   A. {qi.get('a', '')}"]
                t.append("")
            if d.get("say_it_yourself"):
                t += ["## 내 말로 설명하기", d["say_it_yourself"], ""]
            if d.get("clair_one_liner"):
                t += [f"> 클레어: {d['clair_one_liner']}", ""]
            files[f"vault/퀘스트/{_clean(slug)}/day-{d['n']}.md"] = "\n".join(t).rstrip() + "\n"

    # ---- sources / books ---------------------------------------------------------
    book_members: dict[str, list[str]] = {}
    for e in edges:
        if e["rel"] == "in_book" and e["dst"].startswith("book:"):
            book_members.setdefault(e["dst"][5:], []).append(e["src"])
    book_of = {s: b for b, ss in book_members.items() for s in ss}
    for n in nodes:
        if n["kind"] != "source":
            continue
        nid = n["id"]
        e = entries.get(nid.split(":", 1)[-1], {})
        s = ["---", f"id: {_yaml(nid)}", "---", "", f"# {n['label_ko']}", "",
             f"- 책: {book_of.get(nid, e.get('book', ''))}"]
        if src_url(nid):
            s.append(f"- 주소: {src_url(nid)}")
        s += ["", n["summary"] or "", ""]
        cs = about.get(nid, [])
        if cs:
            s += ["## 개념", *[f"- {link(c)}" for c in cs], ""]
        files[f"vault/자료/{src_stem(nid)}.md"] = "\n".join(s).rstrip() + "\n"

    titles = {b.get("slug"): b.get("title") or b.get("slug") for b in store.list_books()}
    for slug in sorted(set(book_members) | set(titles)):
        if not slug:
            continue
        mem = sorted(book_members.get(slug, []))
        cs = sorted({c for m in mem for c in about.get(m, [])})
        b = [f"# {titles.get(slug, slug)}", "", "## 자료",
             *[f"- [[{src_stem(m)}]]" for m in mem], "", "## 개념",
             *[f"- {link(c)}" for c in cs], ""]
        files[f"vault/서재/{book_stem[slug]}.md"] = "\n".join(b).rstrip() + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text.encode("utf-8"))
    return buf.getvalue()
