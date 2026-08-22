from pathlib import Path
from sync import notebooklm_import as ni


class FakeClient:
    def list_sources(self, nb): return [{"id": "s1", "title": "양자 논문"}]
    def get_source_text(self, nb, sid): return "파동함수 ψ"
    def list_notes(self, nb): return [{"id": "n1", "title": "내 정리", "text": "중첩이란..."}]


def test_fetch_items_collects_sources_and_notes():
    items = ni.fetch_items("fd7a", FakeClient())
    kinds = sorted(i["kind"] for i in items)
    assert kinds == ["note", "source"] and items[0]["text"]


def test_write_items_is_idempotent(tmp_path):
    items = ni.fetch_items("fd7a", FakeClient())
    first = ni.write_items(items, tmp_path)
    second = ni.write_items(items, tmp_path)
    assert len(first) == 2 and second == []
    assert (tmp_path / "nblm-source-s1.md").read_text("utf-8").startswith("# 양자 논문")


def test_notebook_id_from_url():
    assert ni.notebook_id("https://notebook.google.com/notebook/fd7a7958-36ea-4dfb-847d-20b96734d58a") == "fd7a7958-36ea-4dfb-847d-20b96734d58a"
    assert ni.notebook_id("abc") == "abc"


class NoteTextClient(FakeClient):
    """A note dict without inline text; text must come from get_note_text()."""
    def list_notes(self, nb): return [{"id": "n2", "title": "제목만"}]
    def get_note_text(self, nb, nid): return "본문은 여기"


def test_fetch_items_falls_back_to_get_note_text():
    items = ni.fetch_items("fd7a", NoteTextClient())
    note = next(i for i in items if i["kind"] == "note")
    assert note["text"] == "본문은 여기"


def test_write_items_sanitizes_id_for_filename(tmp_path):
    items = [{"kind": "source", "id": "weird/id?with*chars", "title": "T", "text": "x"}]
    paths = ni.write_items(items, tmp_path)
    assert len(paths) == 1
    assert paths[0].name == "nblm-source-weird-id-with-chars.md"


def test_write_items_rewrites_when_content_changes(tmp_path):
    items = ni.fetch_items("fd7a", FakeClient())
    ni.write_items(items, tmp_path)
    items[0]["text"] = "달라진 내용"
    changed = ni.write_items(items, tmp_path)
    assert len(changed) == 1
    assert "달라진 내용" in (tmp_path / "nblm-source-s1.md").read_text("utf-8")


def test_make_client_without_package_raises_friendly_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "notebooklm":
            raise ImportError("no module named notebooklm")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        ni.make_client()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "notebooklm-py" in str(e) and "pip install" in str(e)
