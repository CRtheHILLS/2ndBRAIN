import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from brain import catalog, config, graph, index, ingest, intake, store
from brain import intake_state as S

T0 = dt.datetime(2026, 10, 19, 21, 40, tzinfo=S.SEOUL)


@pytest.fixture
def env(data_dir, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "5347359916")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret-token")
    config.get_settings.cache_clear()
    ocr_state = {"value": "done"}
    calls = []

    def fake_ingest(slug, filename, data, extra_meta=None):
        raw = store.raw_dir(slug)
        (raw / filename).write_bytes(data)
        out = raw / (Path(filename).stem + ".md")
        sha = hashlib.sha256(data).hexdigest()
        store.write_md(out, {"book": slug, "source": filename, "sha256": sha, "kind": "image",
                             "ocr": ocr_state["value"], **(extra_meta or {})}, "본문")
        catalog.register(slug, filename, out, sha)
        calls.append((slug, filename, extra_meta))
        return out

    rebuilds = []
    monkeypatch.setattr(ingest, "ingest_file", fake_ingest)
    monkeypatch.setattr(index, "rebuild", lambda: rebuilds.append(1) or 0)
    store.upsert_book("손자병법", "손자병법")
    store.upsert_book("창세기", "창세기")
    return {"calls": calls, "ocr": ocr_state, "rebuilds": rebuilds, "dir": data_dir}


def img(n: int) -> bytes:
    return f"fake-jpeg-{n}".encode()


def at(seconds: float) -> dt.datetime:
    return T0 + dt.timedelta(seconds=seconds)


# --- titles -----------------------------------------------------------------

def test_match_title_exact_similar_new(env):
    assert intake.match_title("손자병법")["kind"] == "exact"
    assert intake.match_title(" 손자병법 ")["slug"] == "손자병법"
    m = intake.match_title("손자 병법")
    assert m["kind"] == "similar"
    assert m["candidates"][0]["slug"] == "손자병법"
    m = intake.match_title("총균쇠")
    assert m == {"kind": "new", "slug": "총균쇠", "title": "총균쇠", "candidates": []}


def test_parse_caption():
    c = intake.parse_caption("손자병법\np.123 #3장 #전략 #리더십\n여기 다시 읽기")
    assert c["title"] == "손자병법"
    assert c["page"] == 123 and c["chapter"] == 3
    assert c["tags"] == ["전략", "리더십"]
    assert c["rest"] == "여기 다시 읽기"
    c = intake.parse_caption("45쪽 2장 좋은 문장")
    assert (c["page"], c["chapter"], c["note"]) == (45, 2, "좋은 문장")


# --- current book & batches -------------------------------------------------

def test_photo_attaches_to_current_book_with_meta(env):
    intake.set_current("손자병법", "손자병법", now=T0)
    r = intake.add_photo(img(1), "", "image/jpeg", caption="p.12 #전략 메모", media_group_id=None, now=at(5))
    assert r["status"] == "attached" and r["slug"] == "손자병법"
    assert r["count"] == 1 and r["dupes"] == 0 and r["ocr"] == "done"
    slug, filename, meta = env["calls"][0]
    assert filename.startswith(f"tg-{r['batch_id']}-1") and filename.endswith(".jpg")
    assert meta["via"] == "telegram" and meta["batch"] == r["batch_id"]
    assert meta["page"] == 12 and meta["tags"] == ["전략"] and meta["note"] == "메모"
    assert r["batch_id"].startswith("b20261019-214005-")


def test_batch_window_90s_sliding_and_10min_cap(env):
    intake.set_current("손자병법", "손자병법", now=T0)
    a = intake.add_photo(img(1), "", "image/jpeg", now=at(0))
    b = intake.add_photo(img(2), "", "image/jpeg", now=at(80))
    c = intake.add_photo(img(3), "", "image/jpeg", now=at(160))
    assert a["batch_id"] == b["batch_id"] == c["batch_id"] and c["count"] == 3
    d = intake.add_photo(img(4), "", "image/jpeg", now=at(160 + 91))
    assert d["batch_id"] != a["batch_id"] and d["count"] == 1
    ids = {intake.add_photo(img(10 + i), "", "image/jpeg", now=at(400 + 80 * i))["batch_id"] for i in range(10)}
    assert len(ids) == 2  # 80 s steps stay within the gap but a batch never spans more than 10 minutes


def test_album_joins_by_media_group(env):
    intake.set_current("손자병법", "손자병법", now=T0)
    ids = {intake.add_photo(img(i), "", "image/jpeg", media_group_id="g1", now=at(i * 200))["batch_id"]
           for i in range(3)}
    assert len(ids) == 1


# --- expiry & holding -------------------------------------------------------

def test_current_expires_after_6h_and_on_date_change(env):
    intake.set_current("손자병법", "손자병법", now=dt.datetime(2026, 10, 19, 9, 0, tzinfo=S.SEOUL))
    assert intake.current(now=dt.datetime(2026, 10, 19, 14, 59, tzinfo=S.SEOUL))["slug"] == "손자병법"
    assert intake.current(now=dt.datetime(2026, 10, 19, 15, 1, tzinfo=S.SEOUL)) is None
    intake.set_current("손자병법", "손자병법", now=dt.datetime(2026, 10, 19, 23, 50, tzinfo=S.SEOUL))
    assert intake.current(now=dt.datetime(2026, 10, 20, 0, 10, tzinfo=S.SEOUL)) is None


def test_last_photo_keeps_current_alive(env):
    intake.set_current("손자병법", "손자병법", now=dt.datetime(2026, 10, 19, 9, 0, tzinfo=S.SEOUL))
    intake.add_photo(img(1), "", "image/jpeg", now=dt.datetime(2026, 10, 19, 14, 0, tzinfo=S.SEOUL))
    assert intake.current(now=dt.datetime(2026, 10, 19, 19, 0, tzinfo=S.SEOUL)) is not None


def test_expired_photo_goes_to_holding_then_resolves(env):
    intake.set_current("손자병법", "손자병법", now=dt.datetime(2026, 10, 18, 22, 0, tzinfo=S.SEOUL))
    r1 = intake.add_photo(img(1), "", "image/jpeg", caption="p.7", now=T0)
    r2 = intake.add_photo(img(2), "", "image/jpeg", now=at(10))
    assert r1["status"] == r2["status"] == "held" and r2["count"] == 2
    assert env["calls"] == []  # nothing attached anywhere
    held = list(S.holding_dir().iterdir())
    assert len(held) == 2
    assert intake.match_title("손자병법")["kind"] == "exact"
    assert intake.book_count("손자병법") == 0
    r = intake.resolve_holding("창세기", "창세기", now=at(60))
    assert r["status"] == "attached" and r["slug"] == "창세기" and r["count"] == 2
    assert intake.book_count("창세기") == 2 and intake.book_count("손자병법") == 0
    assert env["calls"][0][2]["page"] == 7
    assert intake.holding_count() == 0 and list(S.holding_dir().iterdir()) == []
    assert intake.current(now=at(70))["slug"] == "창세기"


def test_discard_holding(env):
    intake.add_photo(img(1), "", "image/jpeg", now=T0)
    assert intake.discard_holding() == 1
    assert intake.holding_count() == 0 and list(S.holding_dir().iterdir()) == []


# --- captions & dupes -------------------------------------------------------

def test_caption_title_overrides_only_that_album(env):
    intake.set_current("창세기", "창세기", now=T0)
    r = intake.add_photo(img(1), "", "image/jpeg", caption="손자병법\np.33", media_group_id="g9", now=at(1))
    r2 = intake.add_photo(img(2), "", "image/jpeg", media_group_id="g9", now=at(2))
    assert r["slug"] == r2["slug"] == "손자병법" and r2["count"] == 2
    assert env["calls"][1][2]["page"] == 33  # first caption applies to the whole album
    assert intake.current(now=at(3))["slug"] == "창세기"
    r3 = intake.add_photo(img(3), "", "image/jpeg", now=at(4))
    assert r3["slug"] == "창세기" and r3["batch_id"] != r["batch_id"]


def test_caption_without_known_title_is_a_note(env):
    intake.set_current("창세기", "창세기", now=T0)
    intake.add_photo(img(1), "", "image/jpeg", caption="이 문장 좋다", now=at(1))
    assert env["calls"][0][0] == "창세기"
    assert env["calls"][0][2]["note"] == "이 문장 좋다"


def test_duplicate_sha_skipped_in_same_book_only(env):
    intake.set_current("손자병법", "손자병법", now=T0)
    intake.add_photo(img(1), "", "image/jpeg", now=at(1))
    r = intake.add_photo(img(1), "", "image/jpeg", now=at(2))
    assert r["count"] == 1 and r["dupes"] == 1 and len(env["calls"]) == 1
    r = intake.add_photo(img(1), "", "image/jpeg", caption="창세기", now=at(3))
    assert r["slug"] == "창세기" and r["count"] == 1 and len(env["calls"]) == 2


def test_ocr_pending_reported(env):
    env["ocr"]["value"] = "pending"
    intake.set_current("손자병법", "손자병법", now=T0)
    assert intake.add_photo(img(1), "", "image/jpeg", now=at(1))["ocr"] == "pending"


# --- move / delete ----------------------------------------------------------

def test_move_batch_moves_files_and_calls_hooks(env, monkeypatch):
    forgot, removed = [], []
    monkeypatch.setattr(catalog, "forget", lambda b, f: forgot.append((b, f)) or True, raising=False)
    monkeypatch.setattr(graph, "remove_node", lambda i: removed.append(i) or True, raising=False)
    intake.set_current("손자병법", "손자병법", now=T0)
    r = intake.add_photo(img(1), "", "image/jpeg", now=at(1))
    intake.add_photo(img(2), "", "image/jpeg", now=at(2))
    b = intake.get_batch(r["batch_id"])
    out = intake.move_batch(r["batch_id"], "총균쇠", "총균쇠")
    assert out["ok"] and out["moved"] == 2 and out["current_switched"]
    assert intake.book_count("손자병법") == 0 and intake.book_count("총균쇠") == 2
    old_raw, new_raw = store.raw_dir("손자병법"), store.raw_dir("총균쇠")
    for f in b["files"]:
        assert not (old_raw / f["file"]).exists()
        assert (new_raw / f["file"]).read_bytes() in (img(1), img(2))
        assert store.read_md(new_raw / f["md"])[0]["book"] == "총균쇠"
    assert [x[0] for x in forgot] == ["손자병법", "손자병법"]
    assert removed[0] == "src:" + catalog.make_id("손자병법", b["files"][0]["file"])[:16]
    assert {i["book"] for i in catalog.queued() if i["file"] == b["files"][0]["file"]} >= {"총균쇠"}
    assert any(x["slug"] == "총균쇠" and x["title"] == "총균쇠" for x in store.list_books())
    assert intake.get_batch(r["batch_id"])["slug"] == "총균쇠"
    assert intake.current(now=at(3))["slug"] == "총균쇠"
    assert env["rebuilds"]


def test_move_batch_works_without_task3_hooks(env, monkeypatch):
    monkeypatch.delattr(catalog, "forget", raising=False)
    monkeypatch.delattr(graph, "remove_node", raising=False)
    intake.set_current("손자병법", "손자병법", now=T0)
    r = intake.add_photo(img(1), "", "image/jpeg", now=at(1))
    assert intake.move_batch(r["batch_id"], "창세기")["moved"] == 1
    assert intake.book_count("창세기") == 1


def test_delete_batch(env, monkeypatch):
    forgot = []
    monkeypatch.setattr(catalog, "forget", lambda b, f: forgot.append((b, f)) or True, raising=False)
    intake.set_current("손자병법", "손자병법", now=T0)
    r = intake.add_photo(img(1), "", "image/jpeg", now=at(1))
    out = intake.delete_batch(r["batch_id"])
    assert out["ok"] and out["deleted"] == 1
    assert intake.book_count("손자병법") == 0
    assert list(store.raw_dir("손자병법").iterdir()) == []
    assert len(forgot) == 1 and intake.get_batch(r["batch_id"]) is None
    assert intake.delete_batch(r["batch_id"])["ok"] is False


# --- state & summary --------------------------------------------------------

def test_state_written_atomically(env):
    intake.set_current("손자병법", "손자병법", now=T0)
    p = S.state_path()
    assert json.loads(p.read_text("utf-8"))["current_book"]["slug"] == "손자병법"
    assert not p.with_name(p.name + ".tmp").exists()


def test_recent_books_and_summary(env):
    intake.set_current("창세기", "창세기", now=T0)
    intake.add_photo(img(1), "", "image/jpeg", now=at(1))
    assert intake.recent_books()[0]["slug"] == "창세기"
    assert {b["slug"] for b in intake.recent_books()} == {"창세기", "손자병법"}
    s = intake.summary()
    assert s["books"][0] == {"slug": "창세기", "title": "창세기", "count": 1}
    assert s["unclassified"] == 1 and s["holding"] == 0
