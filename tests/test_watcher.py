import sys
from pathlib import Path
import pytest
from sync import watcher


class Fake:
    def __init__(self):
        self.calls = []

    def upload(self, book, path):
        self.calls.append((book, path.name))


def test_sync_once_uploads_new_only(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    (tmp_path / "코스모스").mkdir()
    (tmp_path / "코스모스" / "p1.jpg").write_bytes(b"x")
    f = Fake()
    assert watcher.sync_once(tmp_path, f) == 1 and f.calls == [("코스모스", "p1.jpg")]
    assert watcher.sync_once(tmp_path, f) == 0


def test_sync_once_uploads_xlsx(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    d = tmp_path / "코스모스"
    d.mkdir()
    (d / "table.xlsx").write_bytes(b"x")
    f = Fake()
    assert watcher.sync_once(tmp_path, f) == 1 and f.calls == [("코스모스", "table.xlsx")]


def test_sync_once_skips_hidden_and_temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    d = tmp_path / "코스모스"
    d.mkdir()
    (d / "p1.jpg").write_bytes(b"x")
    (d / ".DS_Store").write_bytes(b"y")
    (d / "~$scratch.jpg").write_bytes(b"z")
    f = Fake()
    assert watcher.sync_once(tmp_path, f) == 1
    assert f.calls == [("코스모스", "p1.jpg")]


def test_sync_once_reuploads_changed_file(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    d = tmp_path / "코스모스"
    d.mkdir()
    p = d / "p1.jpg"
    p.write_bytes(b"x")
    f = Fake()
    assert watcher.sync_once(tmp_path, f) == 1
    p.write_bytes(b"changed")
    assert watcher.sync_once(tmp_path, f) == 1
    assert f.calls == [("코스모스", "p1.jpg"), ("코스모스", "p1.jpg")]


def test_main_uses_token_from_env_when_flag_omitted(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setenv("BRAIN_TOKEN", "env-token")
    monkeypatch.setattr(sys, "argv", ["brain-sync", "--root", str(tmp_path), "--url", "http://x", "--once"])
    captured = {}

    class FakeClient:
        def __init__(self, url, token):
            captured["url"], captured["token"] = url, token

        def upload(self, book, path):
            pass

    monkeypatch.setattr(watcher, "UploadClient", FakeClient)
    watcher.main()
    assert captured["token"] == "env-token"


def test_main_requires_token_when_both_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["brain-sync", "--root", str(tmp_path), "--url", "http://x", "--once"])
    with pytest.raises(SystemExit):
        watcher.main()


def test_sync_once_skips_non_book_top_level_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    for folder, fname in [("Claire-models2", "x.png"), ("Clair", "y.png"),
                          ("casting", "z.png"), ("_internal", "w.png")]:
        d = tmp_path / folder
        d.mkdir()
        (d / fname).write_bytes(b"x")
    book = tmp_path / "양자역학"
    book.mkdir()
    (book / "a.txt").write_bytes(b"x")

    f = Fake()
    assert watcher.sync_once(tmp_path, f) == 1
    assert f.calls == [("양자역학", "a.txt")]


def test_sync_once_honours_custom_excludes(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    for folder in ("사진", "코스모스"):
        d = tmp_path / folder
        d.mkdir()
        (d / "a.txt").write_bytes(b"x")
    f = Fake()
    assert watcher.sync_once(tmp_path, f, ["사진"]) == 1
    assert f.calls == [("코스모스", "a.txt")]


def test_excluded_folders_are_skipped_at_any_depth(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    deep = tmp_path / "Claire-models2" / "round1"
    deep.mkdir(parents=True)
    (deep / "x.png").write_bytes(b"x")
    f = Fake()
    assert watcher.sync_once(tmp_path, f) == 0
    assert f.calls == []


def test_default_excludes_match_the_non_book_folders():
    assert watcher.DEFAULT_EXCLUDES == ["_*", "Clair*", "casting"]
    for name in ("_tmp", "Clair", "Claire", "Claire-models2", "casting"):
        assert watcher.is_excluded(name)
    for name in ("양자역학", "코스모스", "Cosmos"):
        assert not watcher.is_excluded(name)


def test_main_passes_exclude_flag_through(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setattr(sys, "argv", ["brain-sync", "--root", str(tmp_path), "--url", "http://x",
                                      "--token", "t", "--once", "--exclude", "사진"])
    captured = {}
    monkeypatch.setattr(watcher, "sync_once",
                        lambda root, client, excludes=None: captured.update(excludes=excludes))
    watcher.main()
    assert captured["excludes"] == ["사진"]
