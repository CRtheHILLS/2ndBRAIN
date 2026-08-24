import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse, PlainTextResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from brain import store, ingest, distill, render, index, levels
from brain.config import get_settings
from brain.ingest import _sanitize_filename
from brain.slug import slugify


CASTING_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>캐스팅 갤러리</title>
<style>
  :root {
    --paper: #faf5ef;
    --card: #ffffff;
    --ink: #3a2e2a;
    --ink-soft: #8a7a70;
    --rose: #c9748c;
    --rose-dark: #a8546c;
    --border: #ecdfd3;
    --shadow: 0 2px 10px rgba(80, 50, 40, 0.08);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --paper: #201a17;
      --card: #2b2320;
      --ink: #f2e8e0;
      --ink-soft: #b6a196;
      --rose: #e592a8;
      --rose-dark: #f2aabd;
      --border: #46392f;
      --shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 16px 16px 96px;
    background: var(--paper);
    color: var(--ink);
    font-family: "Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", -apple-system, sans-serif;
    line-height: 1.5;
  }
  h1 {
    font-size: 1.4rem;
    margin: 8px 0 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  button {
    font: inherit;
    cursor: pointer;
    border: none;
    border-radius: 10px;
    padding: 10px 14px;
    min-height: 40px;
  }
  .refresh-btn {
    background: var(--card);
    color: var(--ink);
    border: 1px solid var(--border);
  }
  .refresh-btn:active { transform: scale(0.97); }
  .delete-btn {
    background: transparent;
    color: var(--rose-dark);
    border: 1px solid var(--rose);
  }
  .delete-btn:active { transform: scale(0.97); }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    box-shadow: var(--shadow);
    padding: 14px;
    margin-bottom: 16px;
  }
  .card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }
  .card-head h2 {
    font-size: 1.1rem;
    margin: 0;
  }
  .pick {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.9rem;
    color: var(--ink-soft);
  }
  .pick input { width: 18px; height: 18px; accent-color: var(--rose); }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: 10px;
  }
  figure {
    margin: 0;
    background: var(--paper);
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--border);
  }
  figure img {
    display: block;
    width: 100%;
    aspect-ratio: 3 / 4;
    object-fit: cover;
    background: var(--border);
  }
  figcaption {
    font-size: 0.78rem;
    color: var(--ink-soft);
    text-align: center;
    padding: 4px 2px;
  }
  .empty {
    color: var(--ink-soft);
    text-align: center;
    padding: 40px 10px;
  }
  #bar {
    position: fixed;
    left: 0; right: 0; bottom: 0;
    background: var(--card);
    border-top: 1px solid var(--border);
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
    box-shadow: 0 -2px 10px rgba(0,0,0,0.06);
    font-size: 0.95rem;
    text-align: center;
  }
  #bar strong { color: var(--rose-dark); }
</style>
</head>
<body>
<h1>📸 캐스팅 갤러리 <button class="refresh-btn" id="refresh">🔄 새로고침</button></h1>
<div id="models"><p class="empty">불러오는 중...</p></div>
<div id="bar">현재 선택: <strong id="picked">아직 없음</strong></div>

<script>
const STORAGE_KEY = "clairCastingPick";

function labelFor(fname) {
  const stem = fname.replace(/\\.[^.]+$/, "").toLowerCase();
  if (stem.includes("face")) return "초근접";
  if (stem.includes("torso")) return "상반신";
  if (stem.includes("back")) return "뒷태";
  return fname;
}

function getToken() {
  let t = localStorage.getItem("brainToken");
  if (!t) {
    t = prompt("토큰을 입력하세요");
    if (t) localStorage.setItem("brainToken", t);
  }
  return t;
}

function updateBar() {
  const picked = localStorage.getItem(STORAGE_KEY);
  document.getElementById("picked").textContent = picked || "아직 없음";
}

function pickModel(name) {
  localStorage.setItem(STORAGE_KEY, name);
  updateBar();
}

async function deleteModel(name) {
  if (!confirm(name + " 폴더 전체를 삭제할까요?")) return;
  const token = getToken();
  if (!token) return;
  const res = await fetch("/casting/" + encodeURIComponent(name), {
    method: "DELETE",
    headers: { "X-Brain-Token": token }
  });
  if (res.status === 401) {
    localStorage.removeItem("brainToken");
    alert("토큰이 올바르지 않아요. 다시 시도해주세요.");
    return;
  }
  if (!res.ok) {
    alert("삭제에 실패했어요.");
    return;
  }
  if (localStorage.getItem(STORAGE_KEY) === name) {
    localStorage.removeItem(STORAGE_KEY);
  }
  await loadAndRender();
}

function renderModels(models) {
  const root = document.getElementById("models");
  root.innerHTML = "";
  if (!models.length) {
    root.innerHTML = '<p class="empty">아직 업로드된 후보가 없어요.</p>';
    return;
  }
  const picked = localStorage.getItem(STORAGE_KEY);
  for (const m of models) {
    const card = document.createElement("div");
    card.className = "card";

    const head = document.createElement("div");
    head.className = "card-head";

    const h2 = document.createElement("h2");
    h2.textContent = m.name;

    const pickWrap = document.createElement("label");
    pickWrap.className = "pick";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "claire-pick";
    radio.value = m.name;
    radio.checked = picked === m.name;
    radio.addEventListener("change", () => pickModel(m.name));
    pickWrap.appendChild(radio);
    pickWrap.appendChild(document.createTextNode("이 사람이 클레어"));

    const delBtn = document.createElement("button");
    delBtn.className = "delete-btn";
    delBtn.textContent = "💔 삭제";
    delBtn.addEventListener("click", () => deleteModel(m.name));

    head.appendChild(h2);
    head.appendChild(pickWrap);
    head.appendChild(delBtn);
    card.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "grid";
    for (const fname of m.files) {
      const fig = document.createElement("figure");
      const img = document.createElement("img");
      img.src = "/casting/img/" + encodeURIComponent(m.name) + "/" + encodeURIComponent(fname);
      img.loading = "lazy";
      img.alt = fname;
      const cap = document.createElement("figcaption");
      cap.textContent = labelFor(fname);
      fig.appendChild(img);
      fig.appendChild(cap);
      grid.appendChild(fig);
    }
    card.appendChild(grid);
    root.appendChild(card);
  }
}

async function loadAndRender() {
  const res = await fetch("/casting/list");
  const data = await res.json();
  renderModels(data.models || []);
  updateBar();
}

document.getElementById("refresh").addEventListener("click", () => loadAndRender());
updateBar();
loadAndRender();
</script>
</body>
</html>
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().brain_token in ("", "change-me"):
        raise RuntimeError("BRAIN_TOKEN must be set")
    render.render_shelf()
    app.mount("/site", StaticFiles(directory=store.site_dir(), html=True), name="site")
    yield


app = FastAPI(title="2nd BRAIN", lifespan=lifespan)


@app.middleware("http")
async def _no_index_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def require_token(x_brain_token: str = Header(default="")):
    if x_brain_token != get_settings().brain_token:
        raise HTTPException(401, "bad token")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/robots.txt")
def robots_txt():
    return PlainTextResponse("User-agent: *\nDisallow: /")


@app.post("/upload", dependencies=[Depends(require_token)])
async def upload(book: str = Form(...), file: UploadFile = File(...)):
    slug = slugify(book)
    store.upsert_book(slug, book)
    try:
        p = ingest.ingest_file(slug, file.filename, await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"slug": slug, "path": str(p)}


@app.post("/books/{slug}/process", dependencies=[Depends(require_token)])
def process(slug: str, level: str = "일반"):
    if slugify(slug) != slug:
        raise HTTPException(400, "bad slug")
    if level not in levels.LEVELS:
        raise HTTPException(400, "bad level")
    if not list(store.raw_dir(slug).glob("*.md")):
        raise HTTPException(400, "책에 아직 자료가 없어요")
    levels.set_level(slug, level)
    try:
        d = distill.distill_book(slug)
    except ValueError as e:
        raise HTTPException(502, str(e))
    # distill just rewrote the notes, so any previously cached level HTML is stale
    render.render_book(slug, default_level=level, use_cache=False)
    n = index.rebuild()
    return {"concepts": len(d["concepts"]), "page": f"/site/{slug}/index.html", "indexed": n}


@app.get("/books")
def books():
    return store.list_books()


@app.get("/search")
def search(q: str, k: int = 10):
    return index.search(q, k)


@app.get("/")
def root():
    return RedirectResponse("/site/index.html")


# ---------------------------------------------------------------------------
# Casting gallery
# ---------------------------------------------------------------------------

_MODEL_CHARS_RE = re.compile(r"[^0-9A-Za-z가-힣 _-]")


def _sanitize_model(model: str) -> str:
    name = _MODEL_CHARS_RE.sub("", model).strip()
    if not name:
        raise HTTPException(400, "invalid model name")
    return name


def _casting_root() -> Path:
    return get_settings().data_dir / "casting"


def _safe_segment(s: str) -> bool:
    return bool(s) and ".." not in s and "/" not in s and "\\" not in s


@app.post("/casting/upload", dependencies=[Depends(require_token)])
async def casting_upload(model: str = Form(...), file: UploadFile = File(...)):
    name = _sanitize_model(model)
    try:
        filename = _sanitize_filename(file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data = await file.read()
    d = _casting_root() / name
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(data)
    return {"model": name, "file": filename}


@app.get("/casting/list")
def casting_list():
    root = _casting_root()
    if not root.exists():
        return {"models": []}
    models = []
    for d in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
        files = sorted(p.name for p in d.iterdir() if p.is_file())
        models.append({"name": d.name, "files": files})
    return {"models": models}


@app.get("/casting/img/{model}/{fname}")
def casting_img(model: str, fname: str):
    if not _safe_segment(model) or not _safe_segment(fname):
        raise HTTPException(404)
    p = _casting_root() / model / fname
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, headers={"cache-control": "no-store"})


@app.delete("/casting/{model}/{fname}", dependencies=[Depends(require_token)])
def casting_delete_file(model: str, fname: str):
    if not _safe_segment(model) or not _safe_segment(fname):
        raise HTTPException(404)
    p = _casting_root() / model / fname
    if not p.is_file():
        raise HTTPException(404)
    p.unlink()
    return {"deleted": fname}


@app.delete("/casting/{model}", dependencies=[Depends(require_token)])
def casting_delete_model(model: str):
    if not _safe_segment(model):
        raise HTTPException(404)
    d = _casting_root() / model
    if not d.is_dir():
        raise HTTPException(404)
    shutil.rmtree(d)
    return {"deleted": model}


@app.get("/casting", response_class=HTMLResponse)
def casting_page():
    return CASTING_HTML
