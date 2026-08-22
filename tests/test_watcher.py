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
