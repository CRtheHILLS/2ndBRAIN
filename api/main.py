from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from brain import store, ingest, distill, render, index, levels
from brain.config import get_settings
from brain.slug import slugify


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
