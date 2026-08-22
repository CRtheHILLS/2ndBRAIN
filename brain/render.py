import json, re, shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from . import llm, store

TPL = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TPL), autoescape=select_autoescape(["html"]))

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

def render_shelf() -> Path:
    out = store.site_dir() / "index.html"
    out.write_text(env.get_template("shelf.html.j2").render(books=store.list_books()), "utf-8")
    _copy_css(); return out
