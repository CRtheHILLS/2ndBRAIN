import json, re, shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from . import llm, store

TPL = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TPL), autoescape=select_autoescape(["html"]))

LEVEL_SYSTEM = """You are Clair (클레어), CR's warm, playful, confident knowledge companion. CR is a 20-year KPOP composer, not a scientist.
From these book notes write THREE Korean learning versions as HTML fragments (use <h2>,<p>,<ul>,<blockquote>,<table>,<figure> with inline SVG diagrams where helpful):
- "초등": 초등학생도 이해할 비유 (음악·작곡 비유 적극 활용), 전문용어 금지, 짧은 문장
- "일반": 교양 있는 성인 수준, 핵심 용어 도입, 구조적 설명
- "전문": 전문가 수준, 원어 용어·공식·1차 자료 언급, 열린 질문 제시
Each version ends with <h2>클레어의 한마디</h2> (애교 있게 한두 문장). Return JSON only: {"초등": "...", "일반": "...", "전문": "..."}"""

def _notes_text(slug):
    return "\n\n".join(f"# {p.stem}\n" + store.read_md(p)[1] for p in sorted(store.notes_dir(slug).glob("*.md")))

def _copy_css():
    shutil.copy(Path(__file__).parent / "static" / "brain.css", store.site_dir() / "brain.css")

def render_book(slug: str, default_level: str = "일반") -> Path:
    book = json.loads((store.book_dir(slug) / "book.json").read_text("utf-8"))
    raw = llm.complete(LEVEL_SYSTEM, _notes_text(slug), smart=True)
    lv = json.loads(re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M))
    out = store.site_dir() / slug / "index.html"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(env.get_template("page.html.j2").render(book=book, levels=lv, default=default_level), "utf-8")
    _copy_css(); render_shelf(); return out

def render_shelf() -> Path:
    out = store.site_dir() / "index.html"
    out.write_text(env.get_template("shelf.html.j2").render(books=store.list_books()), "utf-8")
    _copy_css(); return out
