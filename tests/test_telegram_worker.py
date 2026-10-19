import pytest

from brain import telegram_worker as w


@pytest.fixture
def rec():
    w.reset()
    calls = []
    w.set_handler(lambda u: calls.append(u))
    yield calls
    w.reset()


def _msg(uid, mg=None, caption=None):
    m = {"message_id": uid, "photo": [{"file_id": "f"}]}
    if mg:
        m["media_group_id"] = mg
    if caption:
        m["caption"] = caption
    return {"update_id": uid, "message": m}


def test_orders_by_update_id(rec):
    for uid in (5, 3, 4):
        w.enqueue({"update_id": uid, "message": {"text": "x"}}, now=0)
    w._tick(0)
    assert [u["update_id"] for u in rec] == [3, 4, 5]


def test_duplicate_update_id_dropped(rec):
    w.enqueue(_msg(1), now=0)
    w.enqueue(_msg(1), now=0)
    assert w.pending_count() == 1
    w._tick(0)
    w.enqueue(_msg(1), now=1)
    w._tick(1)
    assert len(rec) == 1


def test_album_waits_window_and_shares_caption(rec):
    w.enqueue(_msg(1, "A"), now=0)
    w.enqueue(_msg(2, "A"), now=0.5)
    w.enqueue(_msg(3, "A", caption="p.12 #3장"), now=1.0)
    w._tick(2.9)
    assert rec == []  # 1.9 s since the last member
    w._tick(3.1)
    assert [u["update_id"] for u in rec] == [1, 2, 3]
    assert [u["message"]["caption"] for u in rec] == ["p.12 #3장"] * 3


def test_later_update_waits_behind_album(rec):
    w.enqueue(_msg(1, "A"), now=0)
    w.enqueue({"update_id": 2, "message": {"text": "hi"}}, now=0.1)
    w._tick(1.0)
    assert rec == []
    w._tick(2.5)
    assert [u["update_id"] for u in rec] == [1, 2]


def test_full_album_released_immediately(rec):
    for i in range(1, 11):
        w.enqueue(_msg(i, "A"), now=0)
    w._tick(0)
    assert len(rec) == 10


def test_handler_exception_does_not_stop_worker(data_dir, rec, monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET:TOKEN")
    from brain import config
    config.get_settings.cache_clear()
    seen = []

    def boom(u):
        seen.append(u["update_id"])
        if u["update_id"] == 1:
            raise RuntimeError("fail SECRET:TOKEN")

    w.set_handler(boom)
    w.enqueue({"update_id": 1, "message": {}}, now=0)
    w.enqueue({"update_id": 2, "message": {}}, now=0)
    w._tick(0)
    assert seen == [1, 2]
    assert "SECRET:TOKEN" not in caplog.text


def test_thread_start_stop_idempotent_and_drain(rec):
    w.start()
    w.start()
    w.enqueue(_msg(1), now=None)
    assert w.drain(5)
    assert len(rec) == 1
    w.stop()
    w.stop()
