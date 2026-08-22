from pathlib import Path
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
