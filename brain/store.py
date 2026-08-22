import json
import datetime as dt
from pathlib import Path

import frontmatter

from .config import get_settings


def _d(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def book_dir(slug):
    return _d(get_settings().data_dir / "books" / slug)


def raw_dir(slug):
    return _d(book_dir(slug) / "raw")


def notes_dir(slug):
    return _d(book_dir(slug) / "notes")


def site_dir():
    return _d(get_settings().data_dir / "site")


def profile_dir():
    return _d(get_settings().data_dir / "profile")


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
    if not root.exists():
        return []
    return [json.loads(p.read_text("utf-8")) for p in sorted(root.glob("*/book.json"))]
