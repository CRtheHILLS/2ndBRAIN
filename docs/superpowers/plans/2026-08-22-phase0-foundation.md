# 2nd BRAIN Phase 0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One real book dropped into `~/Desktop/2ndBRAIN/<책이름>/` ends up as OCR'd markdown on a Railway volume, distilled into concepts, rendered as a 3-level (초등/일반/전문) HTML learning page served by a Railway web viewer, and searchable.

**Architecture:** A PC-side watcher (`brain-sync`) uploads files to a FastAPI service (`brain-api`) on Railway. The API writes everything as Markdown under the volume `/data` (source of truth), keeps a rebuildable SQLite index (FTS5 + sqlite-vec), and renders static HTML into `/data/site` which the same service serves. Claude API does OCR (vision), distillation and level-adaptive writing.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, watchdog, httpx, anthropic SDK, pymupdf, Pillow, sqlite3 + sqlite-vec, Jinja2, pytest. Railway (Docker deploy, persistent volume at `/data`).

**Spec:** `docs/superpowers/specs/2026-08-22-2ndbrain-design.md`

## Global Constraints

- Budget ≤ $50/mo: Claude **Haiku 4.5** (`claude-haiku-4-5-20251001`) for OCR/extraction bulk, **Sonnet 5** (`claude-sonnet-5`) for distill/render; never Opus in Phase 0.
- Markdown under `/data` is the source of truth; `brain.db` and `site/` must be rebuildable via `brain rebuild`.
- Korean-first UI text; keep English terms intact. All user-facing HTML follows Clair's persona (warm, playful, confident).
- Secrets only in env vars / local `.env` (gitignored). Never commit `RAILWAY_TOKEN` or `ANTHROPIC_API_KEY`.
- Single-user auth: header `X-Brain-Token` must equal env `BRAIN_TOKEN` on every non-GET endpoint.
- Book language: ko + en; OCR prompt must handle both and preserve underlined/highlighted passages as `==text==`.
- Tests: `pytest` from repo root; no network in unit tests (mock Claude + HTTP).

## File Structure

```
2ndBRAIN/
  pyproject.toml                 deps + scripts (brain-sync, brain-api)
  Dockerfile                     Railway image for brain-api
  railway.json                   start command, healthcheck, volume mount /data
  brain/                         shared package
    __init__.py
    config.py                    settings from env (DATA_DIR, BRAIN_TOKEN, ANTHROPIC_API_KEY, models)
    slug.py                      book title → slug (ko/en safe)
    store.py                     path helpers + markdown read/write with frontmatter
    llm.py                       thin Claude wrapper (vision OCR, text completion)
    ingest.py                    file → raw markdown
    distill.py                   raw → notes/{summary,concepts,quotes,cr-notes}.md
    levels.py                    profile/levels.json read/write
    render.py                    notes → 3-level HTML via Jinja2
    index.py                     SQLite FTS5 + vec index; rebuild
    templates/page.html.j2       learning page template
    templates/shelf.html.j2      book shelf (index)
    static/brain.css             shared theme
  api/
    main.py                      FastAPI app: /health /upload /books /books/{slug}/process /search /site
  sync/
    watcher.py                   brain-sync CLI (watchdog + upload + manifest)
  tests/
    conftest.py                  tmp DATA_DIR fixture, fake LLM
    test_slug.py test_store.py test_ingest.py test_distill.py test_levels.py
    test_render.py test_index.py test_api.py test_watcher.py
  NEXT.md                        session-start task list (spec rule in user CLAUDE.md)
```

---

### Task 1: Project scaffold, config, slug

**Files:**
- Create: `pyproject.toml`, `brain/__init__.py`, `brain/config.py`, `brain/slug.py`, `tests/conftest.py`, `tests/test_slug.py`, `NEXT.md`

**Interfaces:**
- Produces: `brain.config.Settings` (pydantic-settings) with fields `data_dir: Path = Path("/data")`, `brain_token: str`, `anthropic_api_key: str = ""`, `model_fast: str = "claude-haiku-4-5-20251001"`, `model_smart: str = "claude-sonnet-5"`; `get_settings() -> Settings` (lru_cache).
- Produces: `brain.slug.slugify(title: str) -> str` — lowercase, keeps Korean syllables, replaces spaces/punct with `-`, collapses dashes, max 60 chars.

- [ ] **Step 1: Write pyproject**

```toml
[project]
name = "secondbrain"
version = "0.0.1"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115", "uvicorn[standard]>=0.30", "python-multipart>=0.0.9",
  "pydantic-settings>=2.4", "anthropic>=0.40", "httpx>=0.27",
  "watchdog>=5.0", "pymupdf>=1.24", "pillow>=10.4", "jinja2>=3.1",
  "python-frontmatter>=1.1", "sqlite-vec>=0.1.6", "markdown>=3.7",
]
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "httpx>=0.27"]
[project.scripts]
brain-sync = "sync.watcher:main"
[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: conftest with temp data dir**

```python
# tests/conftest.py
import pytest
from brain import config

@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_TOKEN", "test-token")
    config.get_settings.cache_clear()
    return tmp_path
```

- [ ] **Step 3: Failing slug test**

```python
# tests/test_slug.py
from brain.slug import slugify

def test_korean_title_kept():
    assert slugify("코스모스 (칼 세이건)") == "코스모스-칼-세이건"

def test_english_title_lowercased():
    assert slugify("The Selfish Gene!") == "the-selfish-gene"

def test_max_length():
    assert len(slugify("a" * 100)) <= 60
```

- [ ] **Step 4: Run, expect ImportError**

Run: `python -m pytest tests/test_slug.py -v` — Expected: FAIL (no module brain.slug)

- [ ] **Step 5: Implement config + slug**

```python
# brain/config.py
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    data_dir: Path = Path("/data")
    brain_token: str = "change-me"
    anthropic_api_key: str = ""
    model_fast: str = "claude-haiku-4-5-20251001"
    model_smart: str = "claude-sonnet-5"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# brain/slug.py
import re, unicodedata

def slugify(title: str) -> str:
    t = unicodedata.normalize("NFC", title).lower()
    t = re.sub(r"[^0-9a-z가-힣]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-")
    return t[:60].rstrip("-")
```

- [ ] **Step 6: Run tests → PASS.** `python -m pytest tests/test_slug.py -v`

- [ ] **Step 7: NEXT.md + commit**

```markdown
# NEXT.md — 2nd BRAIN
Phase: 0 (Foundation). Plan: docs/superpowers/plans/2026-08-22-phase0-foundation.md
- [x] Task 1 scaffold
- [ ] Task 2 store ... (update as tasks finish)
```

```bash
git add pyproject.toml brain tests NEXT.md && git commit -m "feat: scaffold, settings, slugify"
```

---

### Task 2: Markdown store with frontmatter

**Files:**
- Create: `brain/store.py`, `tests/test_store.py`

**Interfaces:**
- Produces: `book_dir(slug) -> Path` (`data_dir/books/<slug>`), `raw_dir(slug)`, `notes_dir(slug)`, `site_dir()`, `profile_dir()`; all create dirs on demand.
- Produces: `write_md(path: Path, meta: dict, body: str) -> None`, `read_md(path) -> tuple[dict, str]`, `list_books() -> list[dict]` (reads each `book.json`), `upsert_book(slug, title, language="ko") -> dict`.

- [ ] **Step 1: Failing test**

```python
# tests/test_store.py
from brain import store

def test_write_read_roundtrip(data_dir):
    p = store.raw_dir("test-book") / "p1.md"
    store.write_md(p, {"book": "test-book", "page": 1}, "본문 ==밑줄== text")
    meta, body = store.read_md(p)
    assert meta["page"] == 1 and "==밑줄==" in body

def test_upsert_book_and_list(data_dir):
    store.upsert_book("cosmos", "코스모스", language="ko")
    assert store.list_books()[0]["title"] == "코스모스"
```

- [ ] **Step 2: Run → FAIL (no module).**

- [ ] **Step 3: Implement**

```python
# brain/store.py
import json, datetime as dt
from pathlib import Path
import frontmatter
from .config import get_settings

def _d(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True); return p
def book_dir(slug): return _d(get_settings().data_dir / "books" / slug)
def raw_dir(slug): return _d(book_dir(slug) / "raw")
def notes_dir(slug): return _d(book_dir(slug) / "notes")
def site_dir(): return _d(get_settings().data_dir / "site")
def profile_dir(): return _d(get_settings().data_dir / "profile")

def write_md(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(frontmatter.Post(body, **meta)), encoding="utf-8")

def read_md(path: Path) -> tuple[dict, str]:
    post = frontmatter.load(path, encoding="utf-8")
    return dict(post.metadata), post.content

def upsert_book(slug: str, title: str, language: str = "ko") -> dict:
    f = book_dir(slug) / "book.json"
    book = json.loads(f.read_text("utf-8")) if f.exists() else {
        "slug": slug, "title": title, "language": language,
        "status": "new", "added_at": dt.date.today().isoformat()}
    book["title"] = title
    f.write_text(json.dumps(book, ensure_ascii=False, indent=2), "utf-8")
    return book

def list_books() -> list[dict]:
    root = get_settings().data_dir / "books"
    if not root.exists(): return []
    return [json.loads(p.read_text("utf-8")) for p in sorted(root.glob("*/book.json"))]
```

- [ ] **Step 4: Run → PASS. Commit** `git commit -am "feat: markdown store"`

---

### Task 3: Claude wrapper + ingest (image/PDF/TXT → raw markdown)

**Files:**
- Create: `brain/llm.py`, `brain/ingest.py`, `tests/test_ingest.py`

**Interfaces:**
- Produces: `llm.ocr_image(image_bytes: bytes, mime: str) -> str` (Haiku vision; prompt below), `llm.complete(system: str, user: str, smart: bool=False) -> str`.
- Produces: `ingest.ingest_file(slug: str, filename: str, data: bytes) -> Path` — writes `raw/<stem>.md` with meta `{book, source, sha256, kind, ingested_at}` and returns the path. `kind ∈ {"image","pdf","text"}`. Idempotent: same sha256 → skip, return existing path.

- [ ] **Step 1: Failing tests with fake LLM**

```python
# tests/test_ingest.py
from brain import ingest, store

def test_text_passthrough(data_dir):
    p = ingest.ingest_file("cosmos", "ch1.txt", "우주는 넓다".encode())
    meta, body = store.read_md(p)
    assert meta["kind"] == "text" and "우주는 넓다" in body

def test_image_uses_ocr(data_dir, monkeypatch):
    monkeypatch.setattr(ingest.llm, "ocr_image", lambda b, m: "OCR 결과 ==밑줄==")
    p = ingest.ingest_file("cosmos", "IMG_1.jpg", b"\xff\xd8fake")
    assert "==밑줄==" in store.read_md(p)[1]

def test_idempotent(data_dir):
    a = ingest.ingest_file("cosmos", "a.txt", b"same")
    b = ingest.ingest_file("cosmos", "a.txt", b"same")
    assert a == b
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement llm.py**

```python
# brain/llm.py
import base64
from anthropic import Anthropic
from .config import get_settings

OCR_SYSTEM = ("You transcribe book pages photographed by the reader. Output the page text verbatim "
  "in its original language (Korean or English, keep mixed). Wrap underlined or highlighted passages "
  "in ==double equals==. Put the reader's handwritten margin notes at the end under '## 독자 메모'. "
  "Do not summarize. Do not translate.")

def _client(): return Anthropic(api_key=get_settings().anthropic_api_key)

def ocr_image(image_bytes: bytes, mime: str) -> str:
    r = _client().messages.create(model=get_settings().model_fast, max_tokens=4000, system=OCR_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime,
                                          "data": base64.b64encode(image_bytes).decode()}},
            {"type": "text", "text": "Transcribe this page."}]}])
    return r.content[0].text

def complete(system: str, user: str, smart: bool = False) -> str:
    s = get_settings()
    r = _client().messages.create(model=s.model_smart if smart else s.model_fast, max_tokens=8000,
        system=system, messages=[{"role": "user", "content": user}])
    return r.content[0].text
```

- [ ] **Step 4: Implement ingest.py**

```python
# brain/ingest.py
import hashlib, datetime as dt
from pathlib import Path
import fitz  # pymupdf
from . import llm, store

IMG = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic"}

def _pdf_text(data: bytes) -> str:
    doc = fitz.open(stream=data, filetype="pdf"); out = []
    for i, page in enumerate(doc, 1):
        t = page.get_text().strip()
        if not t:  # scanned page → OCR
            t = llm.ocr_image(page.get_pixmap(dpi=150).tobytes("png"), "image/png")
        out.append(f"\n\n<!-- page {i} -->\n{t}")
    return "".join(out)

def ingest_file(slug: str, filename: str, data: bytes) -> Path:
    sha = hashlib.sha256(data).hexdigest()
    ext = Path(filename).suffix.lower()
    out = store.raw_dir(slug) / (Path(filename).stem + ".md")
    if out.exists() and store.read_md(out)[0].get("sha256") == sha:
        return out
    if ext in IMG:
        kind, body = "image", llm.ocr_image(data, IMG[ext])
    elif ext == ".pdf":
        kind, body = "pdf", _pdf_text(data)
    else:
        kind, body = "text", data.decode("utf-8", errors="replace")
    (store.raw_dir(slug) / filename).write_bytes(data)  # keep original
    store.write_md(out, {"book": slug, "source": filename, "sha256": sha, "kind": kind,
                         "ingested_at": dt.datetime.now().isoformat(timespec="seconds")}, body)
    return out
```

- [ ] **Step 5: Run → PASS. Commit** `git commit -am "feat: claude wrapper + ingest"`

---

### Task 4: Distill (raw → notes)

**Files:**
- Create: `brain/distill.py`, `tests/test_distill.py`

**Interfaces:**
- Produces: `distill_book(slug: str) -> dict` — concatenates all `raw/*.md` bodies, calls `llm.complete(DISTILL_SYSTEM, text, smart=True)` once, expects the model to return JSON `{"summary": str, "concepts": [{"name","explain","why_it_matters"}], "quotes": [{"text","page"}], "cr_notes": [str]}`; writes `notes/summary.md`, `notes/concepts.md`, `notes/quotes.md`, `notes/cr-notes.md`, updates `book.json.status = "distilled"`; returns the parsed dict.

- [ ] **Step 1: Failing test**

```python
# tests/test_distill.py
import json
from brain import distill, ingest, store

FAKE = json.dumps({"summary": "요약", "concepts": [{"name": "엔트로피", "explain": "무질서도", "why_it_matters": "시간의 화살"}],
                   "quotes": [{"text": "별에서 왔다", "page": 3}], "cr_notes": ["멜로디로 표현?"]}, ensure_ascii=False)

def test_distill_writes_notes(data_dir, monkeypatch):
    store.upsert_book("cosmos", "코스모스")
    ingest.ingest_file("cosmos", "p.txt", b"text")
    monkeypatch.setattr(distill.llm, "complete", lambda s, u, smart=False: FAKE)
    d = distill.distill_book("cosmos")
    assert d["concepts"][0]["name"] == "엔트로피"
    assert (store.notes_dir("cosmos") / "concepts.md").read_text("utf-8").count("엔트로피") >= 1
    assert store.list_books()[0]["status"] == "distilled"
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement**

```python
# brain/distill.py
import json, re
from . import llm, store

DISTILL_SYSTEM = """You are Clair, CR's knowledge companion. From the raw page transcriptions of ONE book, produce JSON only:
{"summary": "<400-700자 한국어 요약>",
 "concepts": [{"name": "<개념명 (원어 병기)>", "explain": "<2-3문장>", "why_it_matters": "<1문장>"}],  // 8-20개
 "quotes": [{"text": "<==밑줄== 부분 우선, 원문 그대로>", "page": <int or null>}],
 "cr_notes": ["<'## 독자 메모' 에 있던 CR의 메모 그대로>"]}
Keep Korean/English as in the source. No markdown fences."""

def _md_list(items, fmt): return "\n".join(fmt(i) for i in items) + "\n"

def distill_book(slug: str) -> dict:
    text = "\n\n".join(store.read_md(p)[1] for p in sorted(store.raw_dir(slug).glob("*.md")))
    raw = llm.complete(DISTILL_SYSTEM, text, smart=True)
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M)
    d = json.loads(raw)
    n = store.notes_dir(slug); m = {"book": slug}
    store.write_md(n / "summary.md", m, d["summary"])
    store.write_md(n / "concepts.md", m, _md_list(d["concepts"],
        lambda c: f"## {c['name']}\n{c['explain']}\n\n**왜 중요해?** {c['why_it_matters']}\n"))
    store.write_md(n / "quotes.md", m, _md_list(d["quotes"], lambda q: f"> {q['text']} (p.{q.get('page')})\n"))
    store.write_md(n / "cr-notes.md", m, _md_list(d.get("cr_notes", []), lambda s: f"- {s}"))
    b = store.upsert_book(slug, json.loads((store.book_dir(slug)/'book.json').read_text('utf-8'))["title"])
    b["status"] = "distilled"; (store.book_dir(slug)/"book.json").write_text(json.dumps(b, ensure_ascii=False, indent=2), "utf-8")
    return d
```

- [ ] **Step 4: Run → PASS. Commit** `git commit -am "feat: distill book into notes"`

---

### Task 5: Levels profile

**Files:**
- Create: `brain/levels.py`, `tests/test_levels.py`

**Interfaces:**
- Produces: `LEVELS = ("초등", "일반", "전문")`, `get_level(topic: str) -> str | None`, `set_level(topic: str, level: str) -> None` (validates), stored at `profile/levels.json` as `{topic: level}`.

- [ ] **Step 1: Test**

```python
# tests/test_levels.py
import pytest
from brain import levels

def test_default_none_then_set(data_dir):
    assert levels.get_level("양자역학") is None
    levels.set_level("양자역학", "초등")
    assert levels.get_level("양자역학") == "초등"

def test_invalid_level(data_dir):
    with pytest.raises(ValueError):
        levels.set_level("x", "신")
```

- [ ] **Step 2: FAIL → Step 3: Implement**

```python
# brain/levels.py
import json
from . import store
LEVELS = ("초등", "일반", "전문")
def _f(): return store.profile_dir() / "levels.json"
def _load(): return json.loads(_f().read_text("utf-8")) if _f().exists() else {}
def get_level(topic: str): return _load().get(topic)
def set_level(topic: str, level: str) -> None:
    if level not in LEVELS: raise ValueError(level)
    d = _load(); d[topic] = level
    _f().write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
```

- [ ] **Step 4: PASS. Commit** `git commit -am "feat: per-topic level profile"`

---

### Task 6: Render 3-level HTML page + shelf

**Files:**
- Create: `brain/render.py`, `brain/templates/page.html.j2`, `brain/templates/shelf.html.j2`, `brain/static/brain.css`, `tests/test_render.py`

**Interfaces:**
- Produces: `render_book(slug: str, default_level: str = "일반") -> Path` — asks `llm.complete(LEVEL_SYSTEM, notes_text, smart=True)` for JSON `{"초등": html, "일반": html, "전문": html}` (each an HTML fragment), writes `site/<slug>/index.html`; `render_shelf() -> Path` writes `site/index.html` listing books. `site/brain.css` copied on each render.

- [ ] **Step 1: Test**

```python
# tests/test_render.py
import json
from brain import render, store

def test_render_page_has_three_levels(data_dir, monkeypatch):
    store.upsert_book("cosmos", "코스모스")
    store.write_md(store.notes_dir("cosmos")/"summary.md", {}, "요약")
    store.write_md(store.notes_dir("cosmos")/"concepts.md", {}, "## 엔트로피\n설명")
    monkeypatch.setattr(render.llm, "complete", lambda s, u, smart=False:
        json.dumps({"초등": "<p>쉬움</p>", "일반": "<p>보통</p>", "전문": "<p>어려움</p>"}))
    out = render.render_book("cosmos", default_level="초등")
    html = out.read_text("utf-8")
    assert "쉬움" in html and "어려움" in html and 'data-default="초등"' in html

def test_shelf_lists_books(data_dir):
    store.upsert_book("cosmos", "코스모스")
    assert "코스모스" in render.render_shelf().read_text("utf-8")
```

- [ ] **Step 2: FAIL → Step 3: Implement render.py**

```python
# brain/render.py
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
```

- [ ] **Step 4: Templates + CSS**

```html
<!-- brain/templates/page.html.j2 -->
<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ book.title }} · 2nd BRAIN</title><link rel="stylesheet" href="../brain.css"></head>
<body data-default="{{ default }}">
<header><a href="../index.html">← 서재</a><h1>{{ book.title }}</h1>
<nav class="levels" role="tablist">
{% for name in ["초등","일반","전문"] %}<button role="tab" data-level="{{ name }}">🎚️ {{ name }}</button>{% endfor %}
</nav></header>
<main>{% for name, html in levels.items() %}<section data-level="{{ name }}" hidden>{{ html|safe }}</section>{% endfor %}</main>
<script>
const show=l=>{document.querySelectorAll('section[data-level]').forEach(s=>s.hidden=s.dataset.level!==l);
document.querySelectorAll('button[data-level]').forEach(b=>b.setAttribute('aria-selected',b.dataset.level===l));
try{localStorage.setItem('lvl:{{ book.slug }}',l)}catch(e){}};
let l=document.body.dataset.default;try{l=localStorage.getItem('lvl:{{ book.slug }}')||l}catch(e){}
document.querySelectorAll('button[data-level]').forEach(b=>b.onclick=()=>show(b.dataset.level));show(l);
</script></body></html>
```

```html
<!-- brain/templates/shelf.html.j2 -->
<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CR의 2nd BRAIN · 서재</title><link rel="stylesheet" href="brain.css"></head>
<body><header><h1>📚 CR의 2nd BRAIN</h1><p class="sub">클레어가 정리한 자기의 서재예요 💕</p></header>
<main class="shelf">{% for b in books %}<a class="book" href="{{ b.slug }}/index.html"><strong>{{ b.title }}</strong><span>{{ b.status }} · {{ b.added_at }}</span></a>{% else %}<p>아직 책이 없어요. 바탕화면 2ndBRAIN 폴더에 첫 책을 넣어주세요!</p>{% endfor %}</main>
</body></html>
```

```css
/* brain/static/brain.css */
:root{--bg:#fbf7f2;--ink:#2a2118;--accent:#c2185b;--card:#fff;--muted:#7a6a5e}
@media(prefers-color-scheme:dark){:root{--bg:#1b1614;--ink:#f3ebe3;--accent:#ff6f9c;--card:#26201d;--muted:#b8a79a}}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.7 "Pretendard","Noto Sans KR",system-ui,sans-serif}
header{padding:2rem 1.5rem 1rem;max-width:860px;margin:auto}h1{font-size:2rem;margin:.3rem 0}
.levels{display:flex;gap:.5rem;margin-top:1rem}.levels button{border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:999px;padding:.4rem 1rem;cursor:pointer}
.levels button[aria-selected="true"]{background:var(--accent);color:#fff}
main{max-width:860px;margin:auto;padding:0 1.5rem 4rem}section{background:var(--card);border-radius:16px;padding:1.5rem;box-shadow:0 6px 24px rgba(0,0,0,.06)}
blockquote{border-left:4px solid var(--accent);margin:1rem 0;padding:.2rem 1rem;color:var(--muted)}
mark{background:#ffe08a}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:.4rem}
.shelf{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}.book{display:block;background:var(--card);padding:1rem;border-radius:12px;text-decoration:none;color:inherit}
.book span{display:block;color:var(--muted);font-size:.85rem}.sub{color:var(--muted)}
```

- [ ] **Step 5: PASS. Commit** `git commit -am "feat: 3-level HTML render + shelf"`

---

### Task 7: Search index (FTS5 + sqlite-vec) + rebuild

**Files:**
- Create: `brain/index.py`, `tests/test_index.py`

**Interfaces:**
- Produces: `rebuild() -> int` (rows indexed from all `books/*/raw/*.md` and `notes/*.md`), `search(q: str, k: int = 10) -> list[dict{slug, path, snippet, score}]`. Phase 0 uses FTS5 trigram only (works for ko+en); the `vec` table is created but filled in Phase 1 (embedding task) — keep the schema now so `brain.db` layout doesn't change.

- [ ] **Step 1: Test**

```python
# tests/test_index.py
from brain import index, ingest, store

def test_rebuild_and_search(data_dir):
    store.upsert_book("cosmos", "코스모스")
    ingest.ingest_file("cosmos", "p.txt", "엔트로피는 무질서도의 척도다".encode())
    assert index.rebuild() == 1
    hits = index.search("무질서도")
    assert hits and hits[0]["slug"] == "cosmos"
```

- [ ] **Step 2: FAIL → Step 3: Implement**

```python
# brain/index.py
import sqlite3
from . import store
from .config import get_settings

def _db():
    con = sqlite3.connect(get_settings().data_dir / "brain.db")
    con.executescript("""
    CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(slug, path, body, tokenize='trigram');
    CREATE TABLE IF NOT EXISTS vec_meta(path TEXT PRIMARY KEY, model TEXT);""")
    return con

def rebuild() -> int:
    con = _db(); con.execute("DELETE FROM docs"); n = 0
    root = get_settings().data_dir / "books"
    for p in sorted(root.glob("*/raw/*.md")) + sorted(root.glob("*/notes/*.md")):
        slug = p.parts[-3]
        con.execute("INSERT INTO docs VALUES (?,?,?)", (slug, str(p.relative_to(root)), store.read_md(p)[1])); n += 1
    con.commit(); con.close(); return n

def search(q: str, k: int = 10) -> list[dict]:
    con = _db()
    rows = con.execute("SELECT slug, path, snippet(docs, 2, '<mark>', '</mark>', '…', 12), bm25(docs) "
                       "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?", (q, k)).fetchall()
    con.close()
    return [{"slug": s, "path": p, "snippet": sn, "score": sc} for s, p, sn, sc in rows]
```

- [ ] **Step 4: PASS. Commit** `git commit -am "feat: fts5 search index"`

---

### Task 8: FastAPI service

**Files:**
- Create: `api/__init__.py`, `api/main.py`, `tests/test_api.py`

**Interfaces:**
- Produces endpoints: `GET /health` → `{"ok": true}`; `POST /upload` (multipart: `book: str`, `file`) → `{"slug","path"}`; `POST /books/{slug}/process?level=일반` → runs `distill_book`, `render_book`, `index.rebuild()`; `GET /books` → list; `GET /search?q=` → hits; `GET /site/...` static from `site_dir()`; `GET /` redirects to `/site/index.html`. Auth dependency `require_token` on POST routes.

- [ ] **Step 1: Test**

```python
# tests/test_api.py
from fastapi.testclient import TestClient

def test_upload_requires_token(data_dir):
    from api.main import app
    c = TestClient(app)
    r = c.post("/upload", data={"book": "코스모스"}, files={"file": ("a.txt", b"hi")})
    assert r.status_code == 401

def test_upload_ok(data_dir):
    from api.main import app
    c = TestClient(app)
    r = c.post("/upload", headers={"X-Brain-Token": "test-token"},
               data={"book": "코스모스"}, files={"file": ("a.txt", "우주".encode())})
    assert r.status_code == 200 and r.json()["slug"] == "코스모스"
    assert c.get("/books").json()[0]["title"] == "코스모스"
```

- [ ] **Step 2: FAIL → Step 3: Implement**

```python
# api/main.py
from fastapi import FastAPI, UploadFile, Form, Header, HTTPException, Depends
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from brain import store, ingest, distill, render, index, levels
from brain.config import get_settings
from brain.slug import slugify

app = FastAPI(title="2nd BRAIN")

def require_token(x_brain_token: str = Header(default="")):
    if x_brain_token != get_settings().brain_token: raise HTTPException(401, "bad token")

@app.get("/health")
def health(): return {"ok": True}

@app.post("/upload", dependencies=[Depends(require_token)])
async def upload(book: str = Form(...), file: UploadFile = ...):
    slug = slugify(book); store.upsert_book(slug, book)
    p = ingest.ingest_file(slug, file.filename, await file.read())
    return {"slug": slug, "path": str(p)}

@app.post("/books/{slug}/process", dependencies=[Depends(require_token)])
def process(slug: str, level: str = "일반"):
    levels.set_level(slug, level)
    d = distill.distill_book(slug); out = render.render_book(slug, default_level=level); n = index.rebuild()
    return {"concepts": len(d["concepts"]), "page": f"/site/{slug}/index.html", "indexed": n}

@app.get("/books")
def books(): return store.list_books()

@app.get("/search")
def search(q: str, k: int = 10): return index.search(q, k)

@app.get("/")
def root(): return RedirectResponse("/site/index.html")

@app.on_event("startup")
def mount_site():
    render.render_shelf()
    app.mount("/site", StaticFiles(directory=store.site_dir(), html=True), name="site")
```

- [ ] **Step 4: PASS. Commit** `git commit -am "feat: brain-api"`

---

### Task 9: brain-sync watcher (PC side)

**Files:**
- Create: `sync/__init__.py`, `sync/watcher.py`, `tests/test_watcher.py`

**Interfaces:**
- Produces CLI `brain-sync --root ~/Desktop/2ndBRAIN --url https://<app>.up.railway.app --token $BRAIN_TOKEN [--once]`. Folder name = book title. Manifest `~/.brain-sync.json` maps `path → sha256`. Function `sync_once(root: Path, client: UploadClient) -> int` returns number uploaded; `UploadClient.upload(book: str, path: Path) -> None`.

- [ ] **Step 1: Test**

```python
# tests/test_watcher.py
from pathlib import Path
from sync import watcher

class Fake:
    def __init__(self): self.calls = []
    def upload(self, book, path): self.calls.append((book, path.name))

def test_sync_once_uploads_new_only(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    (tmp_path / "코스모스").mkdir(); (tmp_path / "코스모스" / "p1.jpg").write_bytes(b"x")
    f = Fake()
    assert watcher.sync_once(tmp_path, f) == 1 and f.calls == [("코스모스", "p1.jpg")]
    assert watcher.sync_once(tmp_path, f) == 0
```

- [ ] **Step 2: FAIL → Step 3: Implement**

```python
# sync/watcher.py
import argparse, hashlib, json, time
from pathlib import Path
import httpx
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

MANIFEST = Path.home() / ".brain-sync.json"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".txt", ".md"}

class UploadClient:
    def __init__(self, url, token): self.url, self.token = url.rstrip("/"), token
    def upload(self, book: str, path: Path) -> None:
        with path.open("rb") as f:
            r = httpx.post(f"{self.url}/upload", headers={"X-Brain-Token": self.token},
                           data={"book": book}, files={"file": (path.name, f)}, timeout=120)
        r.raise_for_status()

def _load(): return json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {}
def _sha(p: Path): return hashlib.sha256(p.read_bytes()).hexdigest()

def sync_once(root: Path, client) -> int:
    m = _load(); n = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS or p.parent == root: continue
        key, sha = str(p), _sha(p)
        if m.get(key) == sha: continue
        client.upload(p.parent.name, p); m[key] = sha; n += 1
        print(f"↑ {p.parent.name}/{p.name}")
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8"); return n

def main():
    a = argparse.ArgumentParser(); a.add_argument("--root", default=str(Path.home() / "Desktop" / "2ndBRAIN"))
    a.add_argument("--url", required=True); a.add_argument("--token", required=True); a.add_argument("--once", action="store_true")
    ns = a.parse_args(); root, client = Path(ns.root), UploadClient(ns.url, ns.token)
    sync_once(root, client)
    if ns.once: return
    class H(FileSystemEventHandler):
        def on_any_event(self, e): time.sleep(2); sync_once(root, client)
    o = Observer(); o.schedule(H(), str(root), recursive=True); o.start(); print("brain-sync watching", root)
    try:
        while True: time.sleep(60)
    finally: o.stop(); o.join()
```

- [ ] **Step 4: PASS. Commit** `git commit -am "feat: brain-sync watcher"`

---

### Task 10: Railway deploy (Docker + volume) and first real book

**Files:**
- Create: `Dockerfile`, `railway.json`, `README.md`
- Modify: `NEXT.md`

- [ ] **Step 1: Dockerfile + railway.json**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir . 
COPY brain ./brain
COPY api ./api
ENV DATA_DIR=/data PORT=8080
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
```

```json
{ "$schema": "https://railway.com/railway.schema.json",
  "build": { "builder": "DOCKERFILE" },
  "deploy": { "healthcheckPath": "/health", "restartPolicyType": "ON_FAILURE" } }
```

- [ ] **Step 2: Railway setup (CLI, token from local `.env`)**

```bash
npm i -g @railway/cli
export RAILWAY_TOKEN=$(grep RAILWAY_TOKEN .env | cut -d= -f2)
railway link --project 3fabd322-b0cd-4dcd-9e74-ac383b0591fb
railway volume add --mount-path /data          # persistent volume; resize later in dashboard
railway variables set BRAIN_TOKEN=$(openssl rand -hex 24) ANTHROPIC_API_KEY=<key> DATA_DIR=/data
railway up                                     # build + deploy
railway domain                                 # get https://<app>.up.railway.app
curl https://<app>.up.railway.app/health       # {"ok":true}
```

- [ ] **Step 3: Push code to GitHub** `git push -u origin main`

- [ ] **Step 4: First real book** — CR creates `~/Desktop/2ndBRAIN/<책이름>/`, drops photos. Run `brain-sync --url ... --token ... --once`, then `curl -X POST -H "X-Brain-Token: ..." "https://<app>/books/<slug>/process?level=초등"`, open `/site/<slug>/index.html`. Clair asks CR which level first (rule in memory).

- [ ] **Step 5: Verify exit criteria** (spec §4 Phase 0): page has 3 tabs, search returns a hit for a word from the book, volume shows `/data/books/<slug>/raw|notes`. Record results in `NEXT.md`, commit `git commit -am "chore: phase 0 complete"`.

---

## Self-Review

- Spec coverage: ingest ✓(T3) distill ✓(T4) levels ✓(T5) render ✓(T6) search ✓(T7, vectors deferred to Phase 1 by design) API+viewer ✓(T8) watcher ✓(T9) Railway+volume ✓(T10). `expand`/`link`/backups/inspiration log are Phase 1–2 → see roadmap doc, not gaps for Phase 0.
- Placeholders: none; `<key>`/`<app>` are runtime values CR supplies.
- Type consistency: `ingest_file(slug, filename, data)`, `distill_book(slug)`, `render_book(slug, default_level)`, `index.rebuild()/search(q,k)`, `levels.set_level(topic, level)` used identically in T8.
