import json, re, shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from . import llm, models, quest, store

TPL = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TPL), autoescape=select_autoescape(["html", "j2"], default=True))

LEVEL_INSTRUCTIONS = {
    "초등": "초등학생도 이해할 비유 (음악·작곡 비유 적극 활용), 전문용어 금지, 짧은 문장",
    "일반": "교양 있는 성인 수준, 핵심 용어 도입, 구조적 설명",
    "전문": "전문가 수준, 원어 용어·공식·1차 자료 언급, 열린 질문 제시",
}

def _level_system(level: str) -> str:
    return f"""You are Clair (클레어), CR's warm, playful, confident knowledge companion. CR is a 20-year KPOP composer, not a scientist.
From these book notes write ONE Korean learning version, for the "{level}" level, as a single HTML fragment
(use <h2>,<p>,<ul>,<blockquote>,<table>,<figure> with inline SVG diagrams where helpful):
- "{level}": {LEVEL_INSTRUCTIONS[level]}
End with <h2>클레어의 한마디</h2> (애교 있게 한두 문장). Return ONLY the HTML fragment for this level, no JSON, no other levels."""

def _notes_text(slug):
    return "\n\n".join(f"# {p.stem}\n" + store.read_md(p)[1] for p in sorted(store.notes_dir(slug).glob("*.md")))

def _copy_css():
    shutil.copy(Path(__file__).parent / "static" / "brain.css", store.site_dir() / "brain.css")

def _strip_fence(html: str) -> str:
    return re.sub(r"^```(html)?|```$", "", html.strip(), flags=re.M).strip()

def _levels_cache_path(slug: str) -> Path:
    return store.notes_dir(slug) / "levels-html.json"

def _generate_levels(slug: str) -> dict:
    notes = _notes_text(slug)
    fragments = {}
    for level in ("초등", "일반", "전문"):
        raw = llm.complete(_level_system(level), notes, smart=True)
        fragments[level] = _strip_fence(raw)
    _levels_cache_path(slug).write_text(json.dumps(fragments, ensure_ascii=False, indent=2), encoding="utf-8")
    return fragments

def render_book(slug: str, default_level: str = "일반", use_cache: bool = True) -> Path:
    book = json.loads((store.book_dir(slug) / "book.json").read_text("utf-8"))
    cache = _levels_cache_path(slug)
    if use_cache and cache.exists():
        lv = json.loads(cache.read_text("utf-8"))
    else:
        lv = _generate_levels(slug)
    out = store.site_dir() / slug / "index.html"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(env.get_template("page.html.j2").render(book=book, levels=lv, default=default_level), "utf-8")
    _copy_css(); render_shelf(); return out

QUEST_STATUS_KO = {"queued": "시작 대기", "running": "배우는 중", "waiting_thinker": "생각 대기 중",
                   "done": "끝났어요", "failed": "멈췄어요"}

def render_shelf() -> Path:
    quests = [{"slug": q["slug"], "title": (q.get("plan") or {}).get("title_ko") or q.get("sentence", q["slug"]),
               "status": QUEST_STATUS_KO.get(q.get("status"), q.get("status", "")),
               "created": (q.get("created_at") or "")[:10]} for q in quest.list_quests()]
    quest_slugs = {q["slug"] for q in quests}  # a quest's book only holds its raw files
    books = [b for b in store.list_books() if b["slug"] not in quest_slugs]
    out = store.site_dir() / "index.html"
    out.write_text(env.get_template("shelf.html.j2").render(books=books, quests=quests), "utf-8")
    _copy_css(); return out

# --- quest pages --------------------------------------------------------------

SVG_TAGS = {"svg", "g", "circle", "rect", "ellipse", "line", "polyline", "polygon", "path", "text",
            "tspan", "title", "defs", "marker"}
_SVG_ATTR = re.compile(r"^[a-zA-Z-]+$")
_SVG_ENTITY = re.compile(r"&#|&(?!(?:amp|lt|gt|quot|apos);)\w+;")
_SVG_BAD_ATTRS = {"href", "style"}

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def _sanitize_svg(svg: str) -> str:
    """Allow-list: parse, keep only simple shapes/text, re-serialize the parsed tree; else ""."""
    s = (svg or "").strip()
    if not s or "<!" in s or _SVG_ENTITY.search(s):
        return ""
    try:
        root = ET.fromstring(s)
    except ET.ParseError:
        return ""
    if _local(root.tag) != "svg":
        return ""
    for el in root.iter():
        if not isinstance(el.tag, str) or _local(el.tag) not in SVG_TAGS:
            return ""
        el.tag = _local(el.tag)  # inline SVG in HTML needs no namespace prefix
        for name, value in el.attrib.items():
            v = re.sub(r"\s+", "", value).lower()
            if (not _SVG_ATTR.match(name) or name.lower().startswith("on") or name.lower() in _SVG_BAD_ATTRS
                    or "javascript:" in v or "url(" in v):
                return ""
    root.attrib.pop("width", None)
    root.attrib.pop("height", None)
    root.attrib.setdefault("viewBox", "0 0 200 120")
    return ET.tostring(root, encoding="unicode")

def _quest_site(slug: str) -> Path:
    d = store.site_dir() / "quests" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d

def load_day(slug: str, n: int) -> dict | None:
    """The validated DayLesson dict of ``days/day-<n>.json``, or None if missing/invalid."""
    p = quest.quest_dir(slug) / "days" / f"day-{n}.json"
    try:
        return models.DayLesson.model_validate_json(p.read_text("utf-8")).model_dump()
    except (OSError, ValueError):
        return None

def _bridges(concept_ids: list[str]) -> list:
    try:
        from . import bridge  # Task 15
        return list(bridge.bridges_for(concept_ids))
    except Exception:  # noqa: BLE001 - no bridge module yet, or it failed: show the empty state
        return []

def _day_numbers(plan: dict) -> list[int]:
    return sorted(d["n"] for d in plan["days"])

def render_quest_day(slug: str, n: int) -> Path:
    plan = quest.load(slug)["plan"]
    lesson = load_day(slug, n)
    if lesson is None:
        raise FileNotFoundError(f"day-{n}.json 이 없거나 형식이 맞지 않음: {slug}")
    nums = _day_numbers(plan)
    i = nums.index(n) if n in nums else -1
    prev_n = nums[i - 1] if i > 0 else None
    next_n = nums[i + 1] if 0 <= i < len(nums) - 1 else None
    for d in lesson["dots"]:
        d["svg"] = _sanitize_svg(d["picture_svg"])
        d["links"] = [u for u in d["sources"] if u.startswith(("http://", "https://"))]
    bridges = _bridges([d["concept_id"] for d in lesson["dots"] if d["concept_id"]])
    out = _quest_site(slug) / f"day-{n}.html"
    out.write_text(env.get_template("quest_day.html.j2").render(
        plan=plan, lesson=lesson, n=n, total=len(nums), prev_n=prev_n, next_n=next_n,
        bridges=bridges), "utf-8")
    _copy_css(); return out

def render_quest(slug: str) -> Path:
    q = quest.load(slug)
    plan = q["plan"]
    ledger = quest.load_ledger(slug)
    days, concept_ids = [], []
    for d in sorted(plan["days"], key=lambda d: d["n"]):
        lesson = load_day(slug, d["n"])
        if lesson:
            concept_ids += [c["concept_id"] for c in lesson["dots"] if c["concept_id"]]
        days.append({"n": d["n"], "big_idea": d["big_idea"], "ready": lesson is not None,
                     "one_line": lesson["big_idea_one_line"] if lesson else ""})
    out = _quest_site(slug) / "index.html"
    out.write_text(env.get_template("quest_index.html.j2").render(
        q=q, plan=plan, days=days, n_ready=sum(d["ready"] for d in days),
        sources=sorted((s for s in ledger.sources if s.fetched), key=lambda s: (s.day, s.dot)),
        ledger=ledger, bridges=_bridges(list(dict.fromkeys(concept_ids)))), "utf-8")
    _copy_css(); render_shelf(); return out
