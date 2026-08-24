import json
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse, PlainTextResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
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
    padding: 0 16px 32px;
    background: var(--paper);
    color: var(--ink);
    font-family: "Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", -apple-system, sans-serif;
    line-height: 1.5;
  }
  #topbar {
    position: sticky;
    top: 0;
    z-index: 10;
    margin: 0 -16px 16px;
    padding: 12px 16px calc(10px + env(safe-area-inset-top));
    background: var(--paper);
    border-bottom: 1px solid var(--border);
  }
  h1 {
    font-size: 1.4rem;
    margin: 0 0 10px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .topbar-controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
  }
  .topbar-buttons { display: flex; gap: 8px; }
  #finalInfo {
    font-size: 0.9rem;
    color: var(--ink-soft);
  }
  #finalInfo strong { color: var(--rose-dark); }
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
  .pause-btn {
    background: var(--card);
    color: var(--ink);
    border: 1px solid var(--rose);
  }
  .pause-btn.is-paused {
    background: var(--rose);
    color: #fff;
    border-color: var(--rose);
  }
  .pause-btn:active { transform: scale(0.97); }
  .pick-btn {
    background: var(--rose);
    color: #fff;
    border: 1px solid var(--rose);
  }
  .pick-btn:active { transform: scale(0.97); }
  .unpick-btn {
    background: transparent;
    color: var(--ink-soft);
    border: 1px solid var(--border);
  }
  .unpick-btn:active { transform: scale(0.97); }
  .delete-btn {
    background: transparent;
    color: var(--rose-dark);
    border: 1px solid var(--rose);
  }
  .delete-btn:active { transform: scale(0.97); }
  .section-title {
    font-size: 1.05rem;
    margin: 4px 0 10px;
    color: var(--rose-dark);
  }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    box-shadow: var(--shadow);
    padding: 14px;
    margin-bottom: 16px;
  }
  .card.is-final { border-color: var(--rose); }
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
  .card-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
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
    cursor: zoom-in;
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
  #lightbox {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: none;
    align-items: center;
    justify-content: center;
    background: rgba(20, 14, 10, 0.88);
    padding: 24px;
  }
  #lightbox.is-open { display: flex; }
  #lightbox img {
    max-width: 95vw;
    max-height: 95vh;
    object-fit: contain;
    border-radius: 8px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
  }
  .lightbox-close,
  .lightbox-nav {
    position: absolute;
    background: rgba(0, 0, 0, 0.5);
    color: #fff;
    border: none;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    cursor: pointer;
  }
  .lightbox-close {
    top: max(16px, env(safe-area-inset-top));
    right: 16px;
    width: 44px;
    height: 44px;
    font-size: 1.2rem;
  }
  .lightbox-nav {
    top: 50%;
    transform: translateY(-50%);
    width: 48px;
    height: 48px;
    font-size: 1.6rem;
  }
  .lightbox-prev { left: 12px; }
  .lightbox-next { right: 12px; }
  .lightbox-caption {
    position: absolute;
    bottom: max(16px, env(safe-area-inset-bottom));
    left: 50%;
    transform: translateX(-50%);
    color: #fff;
    background: rgba(0, 0, 0, 0.5);
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 0.85rem;
    max-width: 90vw;
    text-align: center;
  }
</style>
</head>
<body>
<div id="topbar">
  <h1>📸 캐스팅 갤러리</h1>
  <div class="topbar-controls">
    <div class="topbar-buttons">
      <button class="pause-btn" id="pauseToggle">⏸️ 생성 멈춤</button>
      <button class="refresh-btn" id="refresh">🔄</button>
    </div>
    <div id="finalInfo">💖 최종 라운드: <strong id="finalCount">0</strong>명</div>
  </div>
</div>
<div id="models"><p class="empty">불러오는 중...</p></div>

<div id="lightbox" aria-hidden="true">
  <button id="lightboxClose" class="lightbox-close" aria-label="닫기" type="button">✕</button>
  <button id="lightboxPrev" class="lightbox-nav lightbox-prev" aria-label="이전 사진" type="button">‹</button>
  <img id="lightboxImg" src="" alt="">
  <button id="lightboxNext" class="lightbox-nav lightbox-next" aria-label="다음 사진" type="button">›</button>
  <div id="lightboxCaption" class="lightbox-caption"></div>
</div>

<script>
let currentState = { paused: false, picked: [], target: 10, active: 0 };

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

async function checkAuth(res) {
  if (res.status === 401) {
    localStorage.removeItem("brainToken");
    alert("토큰이 올바르지 않아요. 다시 시도해주세요.");
    return false;
  }
  return true;
}

function renderTopbar() {
  const btn = document.getElementById("pauseToggle");
  btn.textContent = currentState.paused ? "▶️ 재개" : "⏸️ 생성 멈춤";
  btn.classList.toggle("is-paused", !!currentState.paused);
  document.getElementById("finalCount").textContent = (currentState.picked || []).length;
}

async function togglePause() {
  const token = getToken();
  if (!token) return;
  const res = await fetch("/casting/state", {
    method: "POST",
    headers: { "X-Brain-Token": token, "Content-Type": "application/json" },
    body: JSON.stringify({ paused: !currentState.paused })
  });
  if (!(await checkAuth(res))) return;
  if (!res.ok) {
    alert("업데이트에 실패했어요.");
    return;
  }
  currentState = await res.json();
  renderTopbar();
}

async function pickModel(name) {
  const token = getToken();
  if (!token) return;
  const res = await fetch("/casting/pick/" + encodeURIComponent(name), {
    method: "POST",
    headers: { "X-Brain-Token": token }
  });
  if (!(await checkAuth(res))) return;
  if (!res.ok) {
    alert("픽에 실패했어요.");
    return;
  }
  await loadAndRender();
}

async function unpickModel(name) {
  const token = getToken();
  if (!token) return;
  const res = await fetch("/casting/unpick/" + encodeURIComponent(name), {
    method: "POST",
    headers: { "X-Brain-Token": token }
  });
  if (!(await checkAuth(res))) return;
  if (!res.ok) {
    alert("되돌리기에 실패했어요.");
    return;
  }
  await loadAndRender();
}

async function deleteModel(name) {
  if (!confirm(name + " 폴더 전체를 삭제할까요?")) return;
  const token = getToken();
  if (!token) return;
  const res = await fetch("/casting/" + encodeURIComponent(name), {
    method: "DELETE",
    headers: { "X-Brain-Token": token }
  });
  if (!(await checkAuth(res))) return;
  if (!res.ok) {
    alert("삭제에 실패했어요.");
    return;
  }
  await loadAndRender();
}

function renderCard(m, isFinal) {
  const card = document.createElement("div");
  card.className = isFinal ? "card is-final" : "card";

  const head = document.createElement("div");
  head.className = "card-head";

  const h2 = document.createElement("h2");
  h2.textContent = m.name;
  head.appendChild(h2);

  const actions = document.createElement("div");
  actions.className = "card-actions";

  if (isFinal) {
    const backBtn = document.createElement("button");
    backBtn.className = "unpick-btn";
    backBtn.textContent = "↩️ 되돌리기";
    backBtn.addEventListener("click", () => unpickModel(m.name));
    actions.appendChild(backBtn);
  } else {
    const pickBtn = document.createElement("button");
    pickBtn.className = "pick-btn";
    pickBtn.textContent = "💖 PICK";
    pickBtn.addEventListener("click", () => pickModel(m.name));
    actions.appendChild(pickBtn);
  }

  const delBtn = document.createElement("button");
  delBtn.className = "delete-btn";
  delBtn.textContent = "💔 삭제";
  delBtn.addEventListener("click", () => deleteModel(m.name));
  actions.appendChild(delBtn);

  head.appendChild(actions);
  card.appendChild(head);

  const grid = document.createElement("div");
  grid.className = "grid";
  m.files.forEach((fname, idx) => {
    const fig = document.createElement("figure");
    const img = document.createElement("img");
    img.src = "/casting/img/" + encodeURIComponent(m.name) + "/" + encodeURIComponent(fname);
    img.loading = "lazy";
    img.alt = fname;
    img.addEventListener("click", () => openLightbox(m.name, m.files, idx));
    const cap = document.createElement("figcaption");
    cap.textContent = labelFor(fname);
    fig.appendChild(img);
    fig.appendChild(cap);
    grid.appendChild(fig);
  });
  card.appendChild(grid);
  return card;
}

let lightboxModel = "";
let lightboxFiles = [];
let lightboxIndex = 0;

function lightboxImgUrl(name, fname) {
  return "/casting/img/" + encodeURIComponent(name) + "/" + encodeURIComponent(fname);
}

function updateLightboxImage() {
  const fname = lightboxFiles[lightboxIndex];
  if (!fname) return;
  const img = document.getElementById("lightboxImg");
  img.src = lightboxImgUrl(lightboxModel, fname);
  img.alt = fname;
  document.getElementById("lightboxCaption").textContent = lightboxModel + " · " + labelFor(fname);
}

function openLightbox(name, files, index) {
  lightboxModel = name;
  lightboxFiles = files;
  lightboxIndex = index;
  updateLightboxImage();
  const box = document.getElementById("lightbox");
  box.classList.add("is-open");
  box.setAttribute("aria-hidden", "false");
}

function closeLightbox() {
  const box = document.getElementById("lightbox");
  box.classList.remove("is-open");
  box.setAttribute("aria-hidden", "true");
}

function isLightboxOpen() {
  return document.getElementById("lightbox").classList.contains("is-open");
}

function lightboxStep(delta) {
  if (!lightboxFiles.length) return;
  lightboxIndex = (lightboxIndex + delta + lightboxFiles.length) % lightboxFiles.length;
  updateLightboxImage();
}

function renderModels(data) {
  const root = document.getElementById("models");
  root.innerHTML = "";
  const picked = data.picked || [];
  const models = data.models || [];

  if (picked.length) {
    const section = document.createElement("div");
    section.className = "section";
    const h2 = document.createElement("h2");
    h2.className = "section-title";
    h2.textContent = "💖 최종 라운드";
    section.appendChild(h2);
    for (const m of picked) section.appendChild(renderCard(m, true));
    root.appendChild(section);
  }

  if (!models.length && !picked.length) {
    root.innerHTML = '<p class="empty">아직 업로드된 후보가 없어요.</p>';
    return;
  }

  for (const m of models) root.appendChild(renderCard(m, false));
}

async function loadAndRender() {
  const [stateRes, listRes] = await Promise.all([
    fetch("/casting/state"),
    fetch("/casting/list")
  ]);
  currentState = await stateRes.json();
  const data = await listRes.json();
  renderTopbar();
  renderModels(data);
}

document.getElementById("refresh").addEventListener("click", () => loadAndRender());
document.getElementById("pauseToggle").addEventListener("click", () => togglePause());
document.getElementById("lightboxClose").addEventListener("click", closeLightbox);
document.getElementById("lightboxPrev").addEventListener("click", () => lightboxStep(-1));
document.getElementById("lightboxNext").addEventListener("click", () => lightboxStep(1));
document.getElementById("lightbox").addEventListener("click", (e) => {
  if (e.target.id === "lightbox") closeLightbox();
});
document.addEventListener("keydown", (e) => {
  if (!isLightboxOpen()) return;
  if (e.key === "Escape") closeLightbox();
  else if (e.key === "ArrowLeft") lightboxStep(-1);
  else if (e.key === "ArrowRight") lightboxStep(1);
});
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


def _is_model_dir(p: Path) -> bool:
    """A model candidate directory: any dir not starting with '_' (the
    leading underscore is reserved for internal files like _state.json)."""
    return p.is_dir() and not p.name.startswith("_")


def _casting_state_path() -> Path:
    return _casting_root() / "_state.json"


def _default_casting_state() -> dict:
    return {"paused": False, "picked": [], "target": 10}


def _load_casting_state() -> dict:
    p = _casting_state_path()
    state = _default_casting_state()
    if not p.is_file():
        return state
    try:
        data = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return state
    if isinstance(data, dict):
        state.update({k: v for k, v in data.items() if k in state})
    return state


def _save_casting_state(state: dict) -> None:
    root = _casting_root()
    root.mkdir(parents=True, exist_ok=True)
    _casting_state_path().write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")


class CastingStateUpdate(BaseModel):
    paused: bool


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


@app.get("/casting/state")
def casting_state():
    state = _load_casting_state()
    picked_set = set(state["picked"])
    root = _casting_root()
    active = 0
    if root.exists():
        active = sum(1 for p in root.iterdir() if _is_model_dir(p) and p.name not in picked_set)
    return {**state, "active": active}


@app.post("/casting/state", dependencies=[Depends(require_token)])
def casting_state_update(body: CastingStateUpdate):
    state = _load_casting_state()
    state["paused"] = body.paused
    _save_casting_state(state)
    return state


@app.post("/casting/pick/{model}", dependencies=[Depends(require_token)])
def casting_pick(model: str):
    if not _safe_segment(model):
        raise HTTPException(404)
    if not (_casting_root() / model).is_dir():
        raise HTTPException(404)
    state = _load_casting_state()
    if model not in state["picked"]:
        state["picked"].append(model)
        _save_casting_state(state)
    return state


@app.post("/casting/unpick/{model}", dependencies=[Depends(require_token)])
def casting_unpick(model: str):
    if not _safe_segment(model):
        raise HTTPException(404)
    state = _load_casting_state()
    if model in state["picked"]:
        state["picked"].remove(model)
        _save_casting_state(state)
    return state


@app.get("/casting/list")
def casting_list():
    root = _casting_root()
    state = _load_casting_state()
    picked_set = set(state["picked"])
    models, picked = [], []
    if root.exists():
        for d in sorted((p for p in root.iterdir() if _is_model_dir(p)), key=lambda p: p.name):
            files = sorted(p.name for p in d.iterdir() if p.is_file())
            item = {"name": d.name, "files": files}
            (picked if d.name in picked_set else models).append(item)
    return {"models": models, "picked": picked}


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
    state = _load_casting_state()
    if model in state["picked"]:
        state["picked"].remove(model)
        _save_casting_state(state)
    return {"deleted": model}


@app.get("/casting", response_class=HTMLResponse)
def casting_page():
    return CASTING_HTML
