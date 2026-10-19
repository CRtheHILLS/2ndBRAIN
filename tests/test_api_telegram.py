import pytest
from fastapi.testclient import TestClient

from brain import config, scheduler, telegram_worker, telegram_bot


@pytest.fixture
def tg(data_dir, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "42")
    monkeypatch.setenv("BRAIN_PUBLIC_URL", "")
    config.get_settings.cache_clear()
    enq = []
    monkeypatch.setattr(telegram_worker, "enqueue", lambda u: enq.append(u))
    return enq


def test_webhook_404_without_token(data_dir, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    config.get_settings.cache_clear()
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/telegram/webhook", json={"update_id": 1})
    assert r.status_code == 404 and "텔레그램" in r.json()["detail"]


def test_webhook_403_bad_secret(tg):
    from api.main import app
    with TestClient(app) as c:
        assert c.post("/telegram/webhook", json={"update_id": 1}).status_code == 403
        r = c.post("/telegram/webhook", json={"update_id": 1},
                   headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
    assert r.status_code == 403 and tg == []


def test_webhook_ok_enqueues(tg):
    from api.main import app
    with TestClient(app) as c:
        r = c.post("/telegram/webhook", json={"update_id": 7},
                   headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert tg == [{"update_id": 7}]


def test_setup_requires_token_and_url(tg, monkeypatch):
    from api.main import app
    with TestClient(app) as c:
        h = {"X-Brain-Token": "test-token"}
        assert c.post("/telegram/setup").status_code == 401
        r = c.post("/telegram/setup", headers=h)  # no public URL
        assert r.status_code == 400 and "주소" in r.json()["detail"]
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        config.get_settings.cache_clear()
        assert c.post("/telegram/setup", headers=h).status_code == 400


def test_setup_calls_telegram(tg, monkeypatch):
    monkeypatch.setenv("BRAIN_PUBLIC_URL", "https://brain.example.com")
    config.get_settings.cache_clear()
    calls = []

    class Fake:
        def __init__(self, token):
            calls.append(("init", token))

        def set_webhook(self, url, secret):
            calls.append(("hook", url, secret))
            return {"ok": True, "w": 1}

        def set_my_commands(self):
            calls.append(("cmds",))
            return {"ok": True, "c": 1}

    monkeypatch.setattr(telegram_bot, "TelegramAPI", Fake)
    from api.main import app
    with TestClient(app) as c:
        calls.clear()  # lifespan also runs setup once
        r = c.post("/telegram/setup", headers={"X-Brain-Token": "test-token"})
    assert r.status_code == 200
    assert r.json() == {"webhook": {"ok": True, "w": 1}, "commands": {"ok": True, "c": 1}}
    assert ("hook", "https://brain.example.com/telegram/webhook", "s3cret") in calls


def test_tick_includes_holding_purged(data_dir, monkeypatch):
    from brain import intake
    monkeypatch.setattr(intake, "purge_holding", lambda h=24: 3, raising=False)
    assert scheduler.tick()["holding_purged"] == 3
    monkeypatch.setattr(intake, "purge_holding", lambda h=24: 1 / 0, raising=False)
    assert scheduler.tick()["holding_purged"] == 0
