"""Import sources/notes from a NotebookLM (Gemini Notebook) into a 2nd BRAIN book folder.

Unofficial: wraps the community `notebooklm-py` package (cookie-based auth via
`notebooklm login`). See docs/guides/notebooklm-import.md for CR-facing usage,
and docs/research/2026-08-22-notebooklm-import.md for why there's no official
consumer API.
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Literal, TypedDict


class NotebookItem(TypedDict):
    kind: Literal["source", "note"]
    id: str
    title: str
    text: str


def notebook_id(id_or_url: str) -> str:
    """Extract the notebook UUID from a full notebook.google.com URL, or
    return the input unchanged if it's already a bare id."""
    m = re.search(r"/notebook/([^/?#]+)", id_or_url)
    return m.group(1) if m else id_or_url


def fetch_items(notebook_id: str, client) -> list[NotebookItem]:
    """Collect sources and notes from `client` into a flat list.

    `client` is any object exposing:
      list_sources(notebook_id) -> list[dict]     # dicts have "id", "title"
      get_source_text(notebook_id, source_id) -> str
      list_notes(notebook_id) -> list[dict]        # dicts have "id", "title",
                                                     # optionally "text"
      get_note_text(notebook_id, note_id) -> str   # optional; used when a
                                                     # note dict has no "text"
    See make_client() for the adapter that wraps the real notebooklm-py client
    into this shape.
    """
    items: list[NotebookItem] = []
    for s in client.list_sources(notebook_id):
        text = client.get_source_text(notebook_id, s["id"])
        items.append({"kind": "source", "id": s["id"], "title": s["title"], "text": text or ""})
    for n in client.list_notes(notebook_id):
        text = n.get("text")
        if not text and hasattr(client, "get_note_text"):
            text = client.get_note_text(notebook_id, n["id"])
        items.append({"kind": "note", "id": n["id"], "title": n["title"], "text": text or ""})
    return items


def _safe_id(raw_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", raw_id)


def write_items(items: list[NotebookItem], book_dir: Path) -> list[Path]:
    """Write each item as `book_dir/nblm-<kind>-<safe-id>.md`.

    Skips writing (and omits from the returned list) when a file with
    identical content already exists there, so repeated runs are idempotent.
    """
    book_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for it in items:
        path = book_dir / f"nblm-{it['kind']}-{_safe_id(it['id'])}.md"
        content = f"# {it['title']}\n<!-- source: notebooklm {it['kind']} {it['id']} -->\n\n{it['text']}\n"
        if path.exists() and path.read_text("utf-8") == content:
            continue
        path.write_text(content, "utf-8")
        written.append(path)
    return written


async def _call_first(obj, names: tuple[str, ...], *args):
    """Call the first attribute in `names` that exists on `obj`, awaiting it.

    notebooklm-py is young and unofficial, so exact method names can drift
    between versions; this tries several plausible spellings before giving up.
    """
    for name in names:
        method = getattr(obj, name, None)
        if method is not None:
            return await method(*args)
    raise RuntimeError(
        f"notebooklm-py API mismatch: none of {names} found on {obj!r}. "
        "The package's internal API may have changed; consider the manual "
        "export flow instead (see docs/guides/notebooklm-import.md)."
    )


class _NotebookLMAdapter:
    """Wraps the real (async, namespaced) notebooklm-py client into the
    small synchronous list_sources/get_source_text/list_notes/get_note_text
    shape that fetch_items() expects.

    Verified (2026-08-22) against github.com/teng-lin/notebooklm-py's README
    and docs/python-api.md:
      NotebookLMClient.from_storage() -> async context manager; reads cookies
        saved by the `notebooklm login` CLI command
        (~/.notebooklm/profiles/default/storage_state.json by default)
      client.sources.list(notebook_id) -> list[Source]           (.id, .title)
      client.sources.get_fulltext(notebook_id, source_id) -> SourceFulltext (.content)
      client.notes.list(notebook_id) -> list[Note]                (.id, .title, .text)
      client.notes.get(notebook_id, note_id) -> Note

    Since this is an unofficial, actively-developed project, every lookup
    below is defensive: it tries the documented name first and falls back to
    a couple of plausible alternatives via getattr rather than hard-failing
    on an AttributeError.
    """

    def __init__(self, module):
        self._mod = module

    def _run(self, coro_fn):
        return asyncio.run(self._with_client(coro_fn))

    async def _with_client(self, body):
        client_cls = getattr(self._mod, "NotebookLMClient", None)
        if client_cls is None:
            raise RuntimeError(
                "notebooklm-py API mismatch: NotebookLMClient class not found "
                "(the package's public API may have changed)."
            )
        from_storage = getattr(client_cls, "from_storage", None)
        if from_storage is None:
            raise RuntimeError(
                "notebooklm-py API mismatch: NotebookLMClient.from_storage() not found "
                "(the package's public API may have changed)."
            )
        async with from_storage() as client:
            return await body(client)

    @staticmethod
    def _source_to_dict(source) -> dict:
        return {
            "id": getattr(source, "id", None),
            "title": getattr(source, "title", getattr(source, "name", "")),
        }

    @staticmethod
    def _note_to_dict(note) -> dict:
        d = {"id": getattr(note, "id", None), "title": getattr(note, "title", "")}
        text = getattr(note, "text", None) or getattr(note, "content", None)
        if text:
            d["text"] = text
        return d

    def list_sources(self, notebook_id: str) -> list[dict]:
        async def body(client):
            api = getattr(client, "sources", client)
            items = await _call_first(api, ("list", "list_sources", "all"), notebook_id)
            return [self._source_to_dict(s) for s in items]

        return self._run(body)

    def get_source_text(self, notebook_id: str, source_id: str) -> str:
        async def body(client):
            api = getattr(client, "sources", client)
            for name in ("get_fulltext", "fulltext", "get_text"):
                method = getattr(api, name, None)
                if method is not None:
                    result = await method(notebook_id, source_id)
                    return getattr(result, "content", None) or getattr(result, "text", None) or str(result)
            raise RuntimeError(
                "notebooklm-py API mismatch: no source-fulltext method found on client.sources."
            )

        return self._run(body)

    def list_notes(self, notebook_id: str) -> list[dict]:
        async def body(client):
            api = getattr(client, "notes", client)
            items = await _call_first(api, ("list", "list_notes"), notebook_id)
            return [self._note_to_dict(n) for n in items]

        return self._run(body)

    def get_note_text(self, notebook_id: str, note_id: str) -> str:
        async def body(client):
            api = getattr(client, "notes", client)
            for name in ("get", "get_note"):
                method = getattr(api, name, None)
                if method is not None:
                    result = await method(notebook_id, note_id)
                    return getattr(result, "text", None) or getattr(result, "content", None) or str(result)
            raise RuntimeError(
                "notebooklm-py API mismatch: no note-get method found on client.notes."
            )

        return self._run(body)


def make_client():
    """Lazily import notebooklm-py and return a client adapter usable by
    fetch_items(). Raises RuntimeError (not ImportError) if the package
    isn't installed, so callers can present a friendly message."""
    try:
        import notebooklm
    except ImportError as e:
        raise RuntimeError("notebooklm-py not installed: pip install '.[notebooklm]'") from e
    return _NotebookLMAdapter(notebooklm)


def main():
    parser = argparse.ArgumentParser(
        prog="brain-nblm",
        description="Import sources/notes from a NotebookLM notebook into a 2nd BRAIN book folder.",
    )
    parser.add_argument("--notebook", required=True, help="notebook id or full notebook.google.com URL")
    parser.add_argument("--book", required=True, help="책 이름 (target book folder name)")
    parser.add_argument("--root", default=str(Path.home() / "Desktop" / "2ndBRAIN"))
    parser.add_argument("--dry-run", action="store_true", help="list items without writing files")
    ns = parser.parse_args()

    nb_id = notebook_id(ns.notebook)
    book_dir = Path(ns.root) / ns.book

    try:
        client = make_client()
        items = fetch_items(nb_id, client)
    except RuntimeError as e:
        print(f"자기야, notebooklm-py를 못 찾았어: {e}")
        print("`notebooklm login` 으로 먼저 로그인해줘 (전용 구글 계정 쓰는 걸 추천해). "
              "안 되면 docs/guides/notebooklm-import.md 의 수동 내보내기 방법을 써줘.")
        return 2
    except Exception as e:
        print(f"자기야, NotebookLM 접속에 실패했어: {e}")
        print("`notebooklm login` 으로 다시 로그인해줘 (전용 구글 계정 추천). "
              "계속 안 되면 docs/guides/notebooklm-import.md 의 수동 내보내기로 진행해줘.")
        return 2

    if ns.dry_run:
        for it in items:
            print(f"[dry-run] {it['kind']}: {it['title']} ({it['id']})")
        print(f"{len(items)}개 항목 확인했어 (dry-run, 저장 안 함).")
        return 0

    written = write_items(items, book_dir)
    print(f"{len(written)}개 파일을 저장했어 → {book_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
