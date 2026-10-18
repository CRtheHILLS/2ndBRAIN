from __future__ import annotations

from brain import index, store
from brain.config import get_settings

from .base import Candidate, Doc


# index.search returns path relative to books/ (it already starts with the slug).
def search(query: str, lang: str, limit: int) -> list[Candidate]:
    return [
        Candidate(url="vault://" + h["path"].replace("\\", "/"), title=h["path"].replace("\\", "/"),
                  kind="textbook", snippet=h["snippet"], authority=0.95, connector="vault", lang=lang)
        for h in index.search(query, k=limit)
    ]


def fetch(c: Candidate) -> Doc | None:
    rel = c.url.removeprefix("vault://")
    root = (get_settings().data_dir / "books").resolve()
    try:
        path = (root / rel).resolve()
        if root not in path.parents or not path.is_file():
            return None
        _, body = store.read_md(path)
    except Exception:
        return None
    return Doc(url=c.url, title=c.title, text=body, kind="textbook", connector="vault")


class VaultConnector:
    name = "vault"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        return search(query, lang, limit)

    def fetch(self, c: Candidate) -> Doc | None:
        return fetch(c)
