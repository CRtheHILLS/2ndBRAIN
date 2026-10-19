import datetime as dt
import hashlib
import itertools
import logging
from pathlib import Path

import httpx
import pytest
import respx

from brain import catalog, config, graph, index, ingest, intake, quest, store, telegram_bot
from brain import intake_state as S

CR = 5347359916
CHAT = 5347359916
TOKEN = "123:secret-token"


class FakeAPI:
    def __init__(self):
        self.calls = []
        self._ids = itertools.count(100)

    def send_message(self, chat_id, text, reply_markup=None):
        mid = next(self._ids)
        self.calls.append({"m": "send", "chat": chat_id, "text": text, "markup": reply_markup, "mid": mid})
        return {"message_id": mid}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        self.calls.append({"m": "edit", "chat": chat_id, "text": text, "markup": reply_markup, "mid": message_id})
        return {}

    def answer_callback_query(self, callback_query_id, text=None):
        self.calls.append({"m": "answer", "text": text})
        return {}

    def get_file(self, file_id):
        return f"bytes-of-{file_id}".encode(), "photos/file_9.jpg", "image/jpeg"

    def of(self, m):
        return [c for c in self.calls if c["m"] == m]

    def button(self, label, call=None):
        """callback_data of the button whose text contains ``label`` in the latest markup that has it."""
        for c in reversed([call] if call else self.calls):
            kb = (c.get("markup") or {}).get("inline_keyboard") or []
            for row in kb:
                for b in row:
                    if label in b["text"]:
                        return b["callback_data"], c
        raise AssertionError(f"no button {label!r}")


class Clock:
    def __init__(self):
        self.t = dt.datetime(2026, 10, 19, 21, 40, tzinfo=S.SEOUL)

    def __call__(self):
        return self.t

    def tick(self, **kw):
        self.t += dt.timedelta(**kw)


@pytest.fixture
def env(data_dir, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", str(CR))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BRAIN_PUBLIC_URL", "https://brain.example")
    config.get_settings.cache_clear()
    ocr_state = {"value": "done"}

    def fake_ingest(slug, filename, data, extra_meta=None):
        raw = store.raw_dir(slug)
        (raw / filename).write_bytes(data)
        out = raw / (Path(filename).stem + ".md")
        sha = hashlib.sha256(data).hexdigest()
        store.write_md(out, {"book": slug, "source": filename, "sha256": sha, "kind": "image",
                             "ocr": ocr_state["value"], **(extra_meta or {})}, "본문")
        catalog.register(slug, filename, out, sha)
        return out

    monkeypatch.setattr(ingest, "ingest_file", fake_ingest)
    monkeypatch.setattr(index, "rebuild", lambda: 0)
    clock = Clock()
    monkeypatch.setattr(S, "now_seoul", clock)
    store.upsert_book("손자병법", "손자병법")
    store.upsert_book("창세기", "창세기")
    return {"api": FakeAPI(), "clock": clock, "ocr": ocr_state, "ids": itertools.count(1)}


def _send(env, **message):
    uid = message.pop("update_id", None) or next(env["ids"])
    msg = {"message_id": 1, "from": {"id": message.pop("sender", CR)}, "chat": {"id": CHAT}, **message}
    upd = {"update_id": uid, "message": msg}
    telegram_bot.handle_update(upd, env["api"])
    return upd


def text(env, t, **kw):
    return _send(env, text=t, **kw)


def photo(env, fid, caption=None, mgid=None):
    m = {"photo": [{"file_id": fid + "-small"}, {"file_id": fid}]}
    if caption:
        m["caption"] = caption
    if mgid:
        m["media_group_id"] = mgid
    return _send(env, **m)


def press(env, data, mid=500):
    upd = {"update_id": next(env["ids"]), "callback_query": {
        "id": "cq", "from": {"id": CR}, "data": data, "message": {"message_id": mid, "chat": {"id": CHAT}}}}
    telegram_bot.handle_update(upd, env["api"])


def press_label(env, label):
    data, call = env["api"].button(label)
    press(env, data, mid=call["mid"])


def set_book(env, title="손자병법"):
    text(env, title)
    env["api"].calls.clear()


# --- auth & idempotency ------------------------------------------------------

def test_unauthorized_user_gets_no_api_calls(env):
    text(env, "손자병법", sender=999)
    _send(env, sender=999, photo=[{"file_id": "x"}])
    press_upd = {"update_id": 77, "callback_query": {"id": "c", "from": {"id": 1}, "data": "k:1",
                                                     "message": {"message_id": 1, "chat": {"id": 1}}}}
    telegram_bot.handle_update(press_upd, env["api"])
    assert env["api"].calls == []
    assert intake.current() is None


def test_no_allowed_id_configured_ignores_everyone(env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "0")
    config.get_settings.cache_clear()
    text(env, "손자병법")
    assert env["api"].calls == []


def test_duplicate_update_id_is_ignored(env):
    set_book(env)
    upd = photo(env, "f1")
    telegram_bot.handle_update(upd, env["api"])
    assert len(env["api"].of("send")) == 1
    assert intake.book_count("손자병법") == 1


# --- choosing a book ----------------------------------------------------------

def test_title_exact_sets_current_book(env):
    text(env, "손자병법")
    (c,) = env["api"].calls
    assert c["text"].startswith("📖 지금 읽는 책: 《손자병법》 (지금까지 0장)")
    assert "6시간 지나면 다시 물어볼게요" in c["text"]
    assert intake.current()["slug"] == "손자병법"


def test_title_similar_offers_three_buttons(env):
    text(env, "손자 병법")
    (c,) = env["api"].calls
    labels = [b["text"] for row in c["markup"]["inline_keyboard"] for b in row]
    assert labels == ["《손자병법》 맞아요", "새 책 《손자 병법》", "취소"]
    assert all(len(b["callback_data"].encode()) <= 64 for row in c["markup"]["inline_keyboard"] for b in row)
    press_label(env, "맞아요")
    assert intake.current()["slug"] == "손자병법"
    assert env["api"].calls[-1]["m"] == "edit" and "지금 읽는 책" in env["api"].calls[-1]["text"]


def test_title_new_creates_book_on_button(env):
    text(env, "총균쇠")
    labels = [b["text"] for row in env["api"].calls[0]["markup"]["inline_keyboard"] for b in row]
    assert labels == ["새 책으로 만들기", "취소"]
    assert not any(b["slug"] == "총균쇠" for b in store.list_books())
    press_label(env, "새 책으로 만들기")
    assert any(b["slug"] == "총균쇠" and b["title"] == "총균쇠" for b in store.list_books())
    assert intake.current()["slug"] == "총균쇠"


def test_existing_title_is_never_overwritten(env):
    text(env, "손자병법")
    assert [b["title"] for b in store.list_books() if b["slug"] == "손자병법"] == ["손자병법"]


def test_book_picker_and_new_book_text_flow(env):
    text(env, telegram_bot.MENU_BOOK)
    labels = [b["text"] for row in env["api"].calls[0]["markup"]["inline_keyboard"] for b in row]
    assert "《손자병법》" in labels and "《창세기》" in labels and "➕ 새 책" in labels
    press_label(env, "➕ 새 책")
    assert "새 책 제목" in env["api"].calls[-1]["text"]
    text(env, "손자 병법")  # similar to an existing title -> ask
    labels = [b["text"] for row in env["api"].calls[-1]["markup"]["inline_keyboard"] for b in row]
    assert labels == ["《손자병법》 맞아요", "새 책 《손자 병법》", "취소"]
    press_label(env, "새 책 《손자 병법》")
    assert intake.current()["slug"] == "손자-병법"


def test_one_shot_button_twice_is_expired(env):
    text(env, "총균쇠")
    data, call = env["api"].button("새 책으로 만들기")
    press(env, data, call["mid"])
    press(env, data, call["mid"])
    assert env["api"].calls[-1] == {"m": "answer", "text": "만료됐어요"}


def test_stale_callback_says_expired_and_nothing_else(env):
    press(env, "k:99999")
    assert env["api"].calls == [{"m": "answer", "text": "만료됐어요"}]


# --- photos -------------------------------------------------------------------

def test_one_photo_one_confirmation(env):
    set_book(env)
    photo(env, "f1")
    (c,) = env["api"].calls
    assert c["m"] == "send"
    assert c["text"].startswith("《손자병법》에 1장 붙였어요 · 지금까지 1장 · 묶음 #1 (10/19 21:40)")
    labels = [b["text"] for row in c["markup"]["inline_keyboard"] for b in row]
    assert labels == ["✅ 맞아요", "🔁 다른 책으로", "🗑 지우기"]


def test_album_of_three_edits_one_confirmation(env):
    set_book(env)
    for i in range(3):
        photo(env, f"a{i}", mgid="album-1")
        env["clock"].tick(seconds=1)
    assert len(env["api"].of("send")) == 1
    edits = env["api"].of("edit")
    assert len(edits) == 2 and edits[-1]["mid"] == env["api"].of("send")[0]["mid"]
    assert "3장 붙였어요" in edits[-1]["text"]
    assert edits[-1]["markup"] == env["api"].of("send")[0]["markup"]  # same keys, no new buttons


def test_photos_90s_apart_join_but_later_ones_start_new_batch(env):
    set_book(env)
    photo(env, "p1")
    env["clock"].tick(seconds=80)
    photo(env, "p2")
    env["clock"].tick(seconds=91)
    photo(env, "p3")
    sends = env["api"].of("send")
    assert len(sends) == 2 and "묶음 #2" in sends[1]["text"]
    assert "2장 붙였어요" in env["api"].of("edit")[0]["text"]


def test_image_document_is_accepted(env):
    set_book(env)
    _send(env, document={"file_id": "d1", "file_name": "page.png", "mime_type": "image/png"})
    assert intake.book_count("손자병법") == 1
    assert any(p.suffix == ".png" for p in store.raw_dir("손자병법").iterdir())


def test_ocr_pending_message(env):
    env["ocr"]["value"] = "pending"
    set_book(env)
    photo(env, "f1")
    assert "📦 사진은 안전하게 보관했어요. 글자는 Clair가 다음 세션에서 읽을게요. (읽기 대기 1장)" \
        in env["api"].calls[0]["text"]


def test_duplicate_photo_is_counted(env):
    set_book(env)
    photo(env, "same")
    photo(env, "same")
    assert intake.book_count("손자병법") == 1
    assert "같은 사진 1장은 건너뛰었어요" in env["api"].calls[-1]["text"]


def test_caption_override_keeps_current_book(env):
    set_book(env, "창세기")
    photo(env, "c1", caption="손자병법\np.12")
    assert intake.book_count("손자병법") == 1 and intake.book_count("창세기") == 0
    assert "지금 읽는 책은 그대로예요" in env["api"].calls[-1]["text"]
    assert intake.current()["slug"] == "창세기"


# --- expiry & holding ----------------------------------------------------------

def test_expired_book_holds_photos_and_asks_once(env):
    env["clock"].t = dt.datetime(2026, 10, 19, 9, 0, tzinfo=S.SEOUL)
    set_book(env)
    env["clock"].tick(hours=6, minutes=1)
    photo(env, "h1")
    photo(env, "h2")
    sends, edits = env["api"].of("send"), env["api"].of("edit")
    assert len(sends) == 1 and len(edits) == 1
    assert sends[0]["text"] == "📥 아까는 《손자병법》이었어요. 이 사진 1장, 어느 책이에요?"
    assert edits[0]["text"] == "📥 아까는 《손자병법》이었어요. 이 사진 2장, 어느 책이에요?"
    labels = [b["text"] for row in sends[0]["markup"]["inline_keyboard"] for b in row]
    assert labels[0] == "《손자병법》 계속" and "➕ 새 책" in labels and "🗑 버리기" in labels
    assert intake.book_count("손자병법") == 0 and intake.holding_count() == 2
    press_label(env, "《창세기》")
    assert intake.book_count("창세기") == 2 and intake.book_count("손자병법") == 0
    assert intake.holding_count() == 0
    last = env["api"].calls[-1]
    assert last["m"] == "edit" and last["mid"] == sends[0]["mid"]
    assert "《창세기》에 2장 붙였어요" in last["text"] and "이제부터 사진은 《창세기》에 붙여요" in last["text"]
    assert intake.current()["slug"] == "창세기"


def test_date_change_says_yesterday(env):
    env["clock"].t = dt.datetime(2026, 10, 19, 23, 50, tzinfo=S.SEOUL)
    set_book(env)
    env["clock"].t = dt.datetime(2026, 10, 20, 0, 5, tzinfo=S.SEOUL)
    photo(env, "n1")
    assert env["api"].calls[0]["text"] == "📥 어제는 《손자병법》이었어요. 이 사진 1장, 어느 책이에요?"
    assert intake.holding_count() == 1


def test_no_book_ever_holds_and_new_book_from_holding(env):
    photo(env, "x1")
    assert env["api"].calls[0]["text"] == "📥 지금 정해진 책이 없어요. 이 사진 1장, 어느 책이에요?"
    press_label(env, "➕ 새 책")
    text(env, "총균쇠")
    assert intake.book_count("총균쇠") == 1 and intake.holding_count() == 0


def test_discard_holding_needs_confirmation(env):
    photo(env, "x1")
    press_label(env, "🗑 버리기")
    assert intake.holding_count() == 1
    press_label(env, "네, 버려요")
    assert intake.holding_count() == 0
    assert env["api"].calls[-1]["text"] == "🗑 보류함 사진 1장을 버렸어요."


# --- fixing batches --------------------------------------------------------------

def test_move_batch_from_confirmation_buttons(env, monkeypatch):
    forgot, removed = [], []
    monkeypatch.setattr(catalog, "forget", lambda b, f: forgot.append((b, f)) or True, raising=False)
    monkeypatch.setattr(graph, "remove_node", lambda i: removed.append(i) or True, raising=False)
    set_book(env)
    photo(env, "m1")
    confirm_mid = env["api"].calls[0]["mid"]
    press_label(env, "🔁 다른 책으로")
    picker = env["api"].calls[-1]
    assert picker["mid"] == confirm_mid and "어느 책으로 옮길까요" in picker["text"]
    labels = [b["text"] for row in picker["markup"]["inline_keyboard"] for b in row]
    assert "《손자병법》" not in labels and "《창세기》" in labels
    press_label(env, "《창세기》")
    assert intake.book_count("창세기") == 1 and intake.book_count("손자병법") == 0
    assert len(forgot) == 1 and len(removed) == 1
    last = env["api"].calls[-1]
    assert last["mid"] == confirm_mid and "《창세기》에 1장 붙였어요" in last["text"]
    assert "지금 읽는 책도 《창세기》로 바꿨어요" in last["text"]


def test_move_from_menu_uses_latest_batch(env):
    set_book(env)
    photo(env, "m1")
    text(env, telegram_bot.MENU_MOVE)
    assert "묶음 #1 (《손자병법》 1장)을 어느 책으로 옮길까요?" in env["api"].calls[-1]["text"]
    press_label(env, "《창세기》")
    assert intake.book_count("창세기") == 1
    assert env["api"].calls[-1]["text"] == "🔁 묶음 #1 1장을 《창세기》로 옮겼어요."


def test_delete_batch_with_confirmation(env, monkeypatch):
    forgot = []
    monkeypatch.setattr(catalog, "forget", lambda b, f: forgot.append((b, f)) or True, raising=False)
    set_book(env)
    photo(env, "d1")
    press_label(env, "🗑 지우기")
    assert intake.book_count("손자병법") == 1
    press_label(env, "네, 지워요")
    assert intake.book_count("손자병법") == 0 and len(forgot) == 1
    assert env["api"].calls[-1]["text"] == "🗑 묶음 #1 사진 1장을 지웠어요."
    data, _ = env["api"].button("✅ 맞아요")
    press(env, data)
    assert env["api"].calls[-1] == {"m": "answer", "text": "만료됐어요"}


def test_confirm_button_removes_buttons(env):
    set_book(env)
    photo(env, "ok1")
    press_label(env, "✅ 맞아요")
    last = env["api"].calls[-1]
    assert last["m"] == "edit" and last["markup"] is None and "✅ 확인했어요." in last["text"]


# --- learn & status ----------------------------------------------------------------

def test_learn_button_starts_quest_with_map_link(env, monkeypatch):
    created, started = [], []

    def fake_create(sentence, days=None, level=None, started_by="cli"):
        created.append((sentence, days, started_by))
        return {"slug": "son-quest", "status": "queued", "existing": False}

    monkeypatch.setattr(quest, "create", fake_create)
    monkeypatch.setattr(quest, "start_background", lambda slug: started.append(slug) or True)
    set_book(env)
    text(env, telegram_bot.MENU_LEARN)
    labels = [b["text"] for row in env["api"].calls[-1]["markup"]["inline_keyboard"] for b in row]
    assert labels == ["7일 퀘스트 시작", "하루 압축", "취소"]
    press_label(env, "7일 퀘스트 시작")
    assert created == [("《손자병법》 책에서 밑줄 친 부분을 중심으로 7일 동안 깊이 이해하고 싶어", 7, "telegram")]
    assert started == ["son-quest"]
    reply = env["api"].calls[-1]["text"]
    assert "https://brain.example/site/quests/son-quest/index.html" in reply
    assert "#t=" not in reply and "test-token" not in reply and TOKEN not in reply


def test_status_menu(env):
    set_book(env)
    photo(env, "s1")
    text(env, telegram_bot.MENU_STATUS)
    t = env["api"].calls[-1]["text"]
    assert t.startswith("📊 서재 현황") and "《손자병법》 1장" in t and "보류함 0장" in t


def test_start_shows_persistent_menu(env):
    text(env, "/start")
    kb = env["api"].calls[0]["markup"]
    assert kb["is_persistent"] and kb["resize_keyboard"]
    assert [b["text"] for row in kb["keyboard"] for b in row] == [
        "📚 책 고르기", "📖 지금 책", "🔁 방금 묶음 옮기기", "🗑 방금 묶음 지우기", "🧠 이 책에서 배우기", "📊 서재 현황"]


def test_korean_particles():
    assert telegram_bot._ro("손자병법") == "으로" and telegram_bot._ro("창세기") == "로"
    assert telegram_bot._ro("하늘") == "로"
    assert telegram_bot._ieot("창세기") == "였어요" and telegram_bot._ieot("손자병법") == "이었어요"
    assert telegram_bot._ieot("Sapiens") == "(이)었어요"


# --- Bot API client -------------------------------------------------------------------

@respx.mock
def test_api_client_payloads_and_token_masking(env, caplog):
    api = telegram_bot.TelegramAPI(TOKEN)
    hook = respx.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True}))
    cmds = respx.post(f"https://api.telegram.org/bot{TOKEN}/setMyCommands").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True}))
    respx.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage").mock(side_effect=httpx.ConnectError(
        f"boom https://api.telegram.org/bot{TOKEN}/sendMessage"))
    respx.post(f"https://api.telegram.org/bot{TOKEN}/getFile").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"file_path": "photos/f_1.jpg"}}))
    respx.get(f"https://api.telegram.org/file/bot{TOKEN}/photos/f_1.jpg").mock(
        return_value=httpx.Response(200, content=b"JPEG"))
    api.set_webhook("https://brain.example/telegram/webhook", "s3cret")
    import json
    body = json.loads(hook.calls[0].request.content)
    assert body == {"url": "https://brain.example/telegram/webhook", "secret_token": "s3cret",
                    "allowed_updates": ["message", "callback_query"]}
    api.set_my_commands()
    names = [c["command"] for c in json.loads(cmds.calls[0].request.content)["commands"]]
    assert names == ["start", "book", "now", "move", "undo", "learn", "status", "help"]
    with caplog.at_level(logging.WARNING):
        assert api.send_message(1, "안녕") == {}
    assert TOKEN not in caplog.text and "***" in caplog.text
    assert api.get_file("abc") == (b"JPEG", "f_1.jpg", "image/jpeg")


# --- review fixes -------------------------------------------------------------

def test_photos_during_new_title_question_wait_for_the_answer(env):
    env["clock"].t = dt.datetime(2026, 10, 19, 9, 0, tzinfo=S.SEOUL)
    set_book(env)  # morning: 손자병법
    env["clock"].t = dt.datetime(2026, 10, 19, 13, 0, tzinfo=S.SEOUL)
    text(env, "사피엔스")
    question = env["api"].calls[-1]
    for i in range(3):
        photo(env, f"s{i}")
    assert intake.book_count("손자병법") == 0 and intake.holding_count() == 3
    last = env["api"].calls[-1]
    assert last["m"] == "edit" and last["mid"] == question["mid"]
    assert last["text"].endswith("📥 사진 3장은 책을 고르면 거기에 붙일게요.")
    assert last["markup"] == question["markup"]
    press_label(env, "새 책으로 만들기")
    assert intake.book_count("사피엔스") == 3 and intake.holding_count() == 0
    assert intake.current()["slug"] == "사피엔스"
    assert "《사피엔스》에 3장 붙였어요" in env["api"].calls[-1]["text"]


def test_cancel_book_question_shows_holding_question(env):
    set_book(env)
    text(env, "사피엔스")
    photo(env, "s1")
    press_label(env, "취소")
    assert env["api"].calls[-1]["text"].endswith("이 사진 1장, 어느 책이에요?")
    assert intake.holding_count() == 1 and intake.book_count("손자병법") == 0


def test_book_picker_holds_photos_until_chosen(env):
    set_book(env)
    text(env, telegram_bot.MENU_BOOK)
    photo(env, "p1")
    assert intake.holding_count() == 1
    press_label(env, "《창세기》")
    assert intake.book_count("창세기") == 1 and intake.book_count("손자병법") == 0


def test_awaiting_title_expires_after_10_minutes(env):
    text(env, telegram_bot.MENU_BOOK)
    press_label(env, "➕ 새 책")
    env["clock"].tick(minutes=11)
    text(env, "총균쇠")
    assert not any(b["slug"] == "총균쇠" for b in store.list_books())  # not created silently
    assert "처음 보는 책이에요" in env["api"].calls[-1]["text"]
    assert S.ui_get("awaiting_title") is None


def test_file_over_20mb_is_refused_without_download(env, monkeypatch):
    downloads = []
    monkeypatch.setattr(env["api"], "get_file", lambda fid: downloads.append(fid))
    set_book(env)
    _send(env, document={"file_id": "big", "file_name": "scan.jpg", "mime_type": "image/jpeg",
                         "file_size": 21 * 1024 * 1024})
    _send(env, photo=[{"file_id": "big2", "file_size": 20 * 1024 * 1024 + 1}])
    assert downloads == []
    assert env["api"].calls[-1]["text"] == ("📎 이 파일은 20MB가 넘어서 받을 수 없어요. "
                                            "사진으로 보내 주시거나 조금 줄여서 보내 주세요.")


def test_duplicate_after_batch_window_opens_no_batch(env):
    set_book(env)
    photo(env, "same")
    env["clock"].tick(seconds=200)
    photo(env, "same")
    photo(env, "same")
    assert len(intake.recent_batches(10)) == 1
    assert env["api"].calls[-2]["text"] == "같은 사진이 이미 《손자병법》에 있어서 1장 건너뛰었어요."
    assert env["api"].calls[-1]["m"] == "edit" and "2장 건너뛰었어요" in env["api"].calls[-1]["text"]


def test_one_day_learn_sentence_differs(env, monkeypatch):
    created = []

    def fake_create(s, days=None, level=None, started_by="cli"):
        created.append(s)
        return {"slug": "q1", "status": "queued", "existing": False}

    monkeypatch.setattr(quest, "create", fake_create)
    monkeypatch.setattr(quest, "start_background", lambda slug: True)
    set_book(env)
    text(env, telegram_bot.MENU_LEARN)
    press_label(env, "하루 압축")
    assert created == ["《손자병법》 책에서 밑줄 친 부분을 중심으로 하루 동안 깊이 이해하고 싶어"]
