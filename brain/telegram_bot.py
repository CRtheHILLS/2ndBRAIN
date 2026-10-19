"""Telegram bot (@SexyClair_bot): update parsing, buttons, messages, Bot API client.

``handle_update(update, api)`` is the single entry point (the webhook route
calls it in a background thread).  Every user-facing string is Korean, in
Clair's voice.  Inline buttons carry short keys (``k:<n>``) that map to
payloads stored in the intake state; unknown keys answer "만료됐어요".
"""

import logging
import mimetypes
import threading
from pathlib import PurePosixPath

import httpx

from . import intake, quest
from . import intake_state as S
from .config import get_settings

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx INFO lines would print the bot token URL

API_BASE = "https://api.telegram.org"
TIMEOUT = 30
MAX_FILE_BYTES = 20 * 1024 * 1024  # Bot API getFile download limit
_UI_LOCK = threading.RLock()  # one confirmation message per batch even when album photos race

MENU_BOOK, MENU_NOW, MENU_MOVE = "📚 책 고르기", "📖 지금 책", "🔁 방금 묶음 옮기기"
MENU_DELETE, MENU_LEARN, MENU_STATUS = "🗑 방금 묶음 지우기", "🧠 이 책에서 배우기", "📊 서재 현황"
MENU = [[MENU_BOOK, MENU_NOW], [MENU_MOVE, MENU_DELETE], [MENU_LEARN, MENU_STATUS]]
COMMANDS = [
    ("start", "시작하기"), ("book", "책 고르기"), ("now", "지금 읽는 책 보기"),
    ("move", "방금 묶음 다른 책으로 옮기기"), ("undo", "방금 묶음 지우기"),
    ("learn", "이 책에서 배우기"), ("status", "서재 현황"), ("help", "사용법"),
]
EXPIRED = "만료됐어요"


# ---------------------------------------------------------------------------
# Bot API client
# ---------------------------------------------------------------------------

class TelegramAPI:
    def __init__(self, token: str):
        self.token = token

    def _mask(self, text: str) -> str:
        return str(text).replace(self.token, "***") if self.token else str(text)

    def _call(self, method: str, payload: dict) -> dict:
        url = f"{API_BASE}/bot{self.token}/{method}"
        try:
            r = httpx.post(url, json=payload, timeout=TIMEOUT)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("텔레그램 %s 실패: %s", method, self._mask(e))
            return {}
        if not data.get("ok"):
            log.warning("텔레그램 %s 거절: %s", method, self._mask(data.get("description", "")))
            return {}
        res = data.get("result")
        return res if isinstance(res, dict) else {"result": res}

    def send_message(self, chat_id, text: str, reply_markup: dict | None = None) -> dict:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", payload)

    def edit_message_text(self, chat_id, message_id, text: str, reply_markup: dict | None = None) -> dict:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call("editMessageText", payload)

    def answer_callback_query(self, callback_query_id, text: str | None = None) -> dict:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._call("answerCallbackQuery", payload)

    def get_file(self, file_id: str) -> tuple[bytes, str, str]:
        info = self._call("getFile", {"file_id": file_id})
        path = info.get("file_path")
        if not path:
            raise RuntimeError("getFile에 file_path가 없어요")
        try:
            r = httpx.get(f"{API_BASE}/file/bot{self.token}/{path}", timeout=TIMEOUT)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(self._mask(e)) from None
        name = PurePosixPath(path).name
        return r.content, name, mimetypes.guess_type(name)[0] or "image/jpeg"

    def set_webhook(self, url: str, secret: str) -> dict:
        return self._call("setWebhook", {"url": url, "secret_token": secret,
                                         "allowed_updates": ["message", "callback_query"]})

    def set_my_commands(self) -> dict:
        return self._call("setMyCommands",
                          {"commands": [{"command": c, "description": d} for c, d in COMMANDS]})


# ---------------------------------------------------------------------------
# keyboards (pure) and texts
# ---------------------------------------------------------------------------

class keyboards:  # noqa: N801 - a namespace of pure functions
    @staticmethod
    def main_menu() -> dict:
        return {"keyboard": [[{"text": t} for t in row] for row in MENU],
                "resize_keyboard": True, "is_persistent": True}

    @staticmethod
    def inline(rows: list[list[tuple[str, str]]]) -> dict:
        return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}

    @staticmethod
    def pairs(buttons: list) -> list[list]:
        """Two buttons per row."""
        return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def _short(title: str, n: int = 18) -> str:
    return title if len(title) <= n else title[:n - 1] + "…"


def _final_consonant(word: str) -> int | None:
    """Index of the last Hangul syllable's final consonant (0 = none); None if not Hangul."""
    ch = (word or "").rstrip("》」』) ")[-1:]
    if not ch or not ("가" <= ch <= "힣"):
        return None
    return (ord(ch) - 0xAC00) % 28


def _ro(title: str) -> str:
    """조사 (으)로: 손자병법으로 / 창세기로 / 하늘로."""
    j = _final_consonant(title)
    return "(으)로" if j is None else ("로" if j in (0, 8) else "으로")


def _ieot(title: str) -> str:
    """조사 이었어요/였어요: 손자병법이었어요 / 창세기였어요 / Sapiens(이)었어요."""
    j = _final_consonant(title)
    return "(이)었어요" if j is None else ("였어요" if j == 0 else "이었어요")


def _book(title: str) -> str:
    return f"《{title}》"


def text_book_set(title: str, count: int) -> str:
    return (f"📖 지금 읽는 책: {_book(title)} (지금까지 {count}장). 사진을 보내면 여기에 붙여요. "
            "6시간 지나면 다시 물어볼게요.")


def text_batch(b: dict, total: int, ocr_waiting: int, note: str = "") -> str:
    when = S.parse(b["created_at"]).astimezone(S.SEOUL).strftime("%m/%d %H:%M")
    n = len(b["files"])
    if n:
        lines = [f"{_book(b['title'])}에 {n}장 붙였어요 · 지금까지 {total}장 · 묶음 #{b['seq']} ({when})"]
    else:
        lines = [f"{_book(b['title'])}에 이미 있는 사진이었어요 · 묶음 #{b['seq']} ({when})"]
    if b.get("dupes"):
        lines.append(f"같은 사진 {b['dupes']}장은 건너뛰었어요.")
    if not b.get("via_current"):
        lines.append("사진 설명에 적힌 책 제목을 보고 이 사진만 여기에 붙였어요. 지금 읽는 책은 그대로예요.")
    pending = sum(1 for f in b["files"] if f.get("ocr") == "pending")
    if pending:
        lines.append("📦 사진은 안전하게 보관했어요. 글자는 Clair가 다음 세션에서 읽을게요. "
                     f"(읽기 대기 {max(ocr_waiting, pending)}장)")
    if b.get("confirmed"):
        lines.append("✅ 확인했어요.")
    if note:
        lines.append(note)
    return "\n".join(lines)


def text_holding(n: int, last: dict | None, now=None) -> str:
    ask = f"이 사진 {n}장, 어느 책이에요?"
    if not last:
        return f"📥 지금 정해진 책이 없어요. {ask}"
    now = now or S.now_seoul()
    days = (now.astimezone(S.SEOUL).date() - S.parse(last["last_at"]).astimezone(S.SEOUL).date()).days
    when = "아까는" if days <= 0 else ("어제는" if days == 1 else "지난번엔")
    return f"📥 {when} {_book(last['title'])}{_ieot(last['title'])}. {ask}"


def text_help() -> str:
    return ("📖 이렇게 쓰면 돼요\n"
            "1. 책 제목을 글로 보내면 '지금 읽는 책'이 돼요.\n"
            "2. 밑줄 친 쪽 사진을 보내면 그 책에 붙여요. 여러 장을 한꺼번에 보내도 돼요.\n"
            "3. 사진 설명 첫 줄에 책 제목을 쓰면 그 사진만 그 책으로 가요. "
            "p.123 이나 123쪽은 쪽수, 3장은 장, #단어는 태그로 적어 둘게요.\n"
            "4. 6시간이 지나거나 날짜가 바뀌면 사진을 보류함에 두고 어느 책인지 먼저 물어볼게요.\n"
            "5. 잘못 붙었으면 🔁 옮기기나 🗑 지우기를 눌러 주세요.\n"
            "사진을 '파일'로 보내면 원본 화질이라 글자를 더 잘 읽어요.")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _kb(rows: list[list[tuple[str, dict]]]) -> dict:
    """Register payloads as one keyboard group and build the inline markup."""
    flat = [p for row in rows for _, p in row]
    keys = iter(S.register_buttons(flat))
    return keyboards.inline([[(t, next(keys)) for t, _ in row] for row in rows])


def _reply(api, chat, mid, text: str, markup: dict | None = None) -> dict:
    if mid:
        return api.edit_message_text(chat, mid, text, reply_markup=markup)
    return api.send_message(chat, text, reply_markup=markup)


def _picker(purpose: str, batch: str | None = None, offset: int = 0, exclude: str | None = None) -> dict:
    books = [b for b in intake.recent_books(n=7, offset=offset) if b["slug"] != exclude][:6]
    more = len(intake.recent_books(n=1, offset=offset + 6)) > 0
    pick = [(f"{_book(_short(b['title']))}", {"a": "pick", "slug": b["slug"], "title": b["title"],
                                             "for": purpose, "batch": batch}) for b in books]
    rows = keyboards.pairs(pick)
    tail = [("➕ 새 책", {"a": "newbook", "for": purpose, "batch": batch})]
    if more:
        tail.append(("🔎 더 보기", {"a": "more", "for": purpose, "batch": batch, "off": offset + 6,
                                    "exclude": exclude}))
    rows.append(tail)
    rows.append([("취소", {"a": "cancel"})])
    return _kb(rows)


def _batch_label(b: dict) -> str:
    return f"묶음 #{b['seq']} ({_book(b['title'])} {len(b['files'])}장)"


def _render_batch(api, b: dict, note: str = "", chat=None) -> None:
    """Send (first photo) or edit (later photos) the single confirmation message of a batch."""
    text = text_batch(b, intake.book_count(b["slug"]), intake.ocr_pending_count(), note)
    markup = None
    if not b.get("confirmed"):
        markup = b.get("kb") or _kb([[("✅ 맞아요", {"a": "ok", "batch": b["id"]}),
                                      ("🔁 다른 책으로", {"a": "mv", "batch": b["id"]}),
                                      ("🗑 지우기", {"a": "del", "batch": b["id"]})]])
        if not b.get("kb"):
            intake.update_batch(b["id"], kb=markup)
    msg = b.get("message")
    if msg:
        api.edit_message_text(msg["chat_id"], msg["message_id"], text, reply_markup=markup)
    elif chat is not None:
        res = api.send_message(chat, text, reply_markup=markup)
        if res.get("message_id") is not None:
            intake.set_batch_message(b["id"], chat, res["message_id"])


def _render_holding(api, chat, mid=None) -> None:
    """One question for everything in holding: send once, then edit its count."""
    n = intake.holding_count()
    slot = S.ui_get("holding_msg")
    if n == 0:
        S.ui_set("holding_msg", None)
        return
    last = intake.last_book()
    if slot and not mid:
        mid, markup = slot["message_id"], slot["markup"]
    else:
        buttons = []
        if last:
            buttons.append((f"{_book(_short(last['title']))} 계속",
                            {"a": "pick", "slug": last["slug"], "title": last["title"], "for": "hold"}))
        for b in intake.recent_books(n=6):
            if (not last or b["slug"] != last["slug"]) and len(buttons) < 6:
                buttons.append((_book(_short(b["title"])),
                                {"a": "pick", "slug": b["slug"], "title": b["title"], "for": "hold"}))
        rows = keyboards.pairs(buttons)
        rows.append([("➕ 새 책", {"a": "newbook", "for": "hold"}), ("🗑 버리기", {"a": "hold_drop"})])
        markup = _kb(rows)
    res = _reply(api, chat, mid, text_holding(n, last), markup)
    mid = mid or res.get("message_id")
    if mid is not None:
        S.ui_set("holding_msg", {"chat_id": chat, "message_id": mid, "markup": markup})


def _learn_confirm(api, chat, mid, slug: str, title: str) -> None:
    rows = [[("7일 퀘스트 시작", {"a": "learn", "slug": slug, "title": title, "days": 7}),
             ("하루 압축", {"a": "learn", "slug": slug, "title": title, "days": 1})],
            [("취소", {"a": "cancel"})]]
    _reply(api, chat, mid, f"🧠 {_book(title)}에서 밑줄 친 부분을 중심으로 배워 볼까요?", _kb(rows))


def _start_learn(api, chat, mid, title: str, days: int) -> None:
    span = "7일 동안" if days >= 7 else "하루 동안"  # distinct sentences: find_existing must not mix them
    sentence = f"《{title}》 책에서 밑줄 친 부분을 중심으로 {span} 깊이 이해하고 싶어"
    q = quest.create(sentence, days=days, started_by="telegram")
    if q.get("status") != "done":
        quest.start_background(q["slug"])
    base = (get_settings().brain_public_url or "").rstrip("/")
    link = f"{base}/site/quests/{q['slug']}/index.html" if base else ""
    kind = "7일 퀘스트" if days >= 7 else "하루 압축 퀘스트"
    head = (f"🧠 {_book(title)} 퀘스트는 이미 만들어 두었어요. 지도는 여기서 볼 수 있어요." if q.get("existing")
            else f"🧠 {_book(title)} {kind}를 시작했어요. 다 되면 이 지도에서 볼 수 있어요.")
    _reply(api, chat, mid, head + (f"\n{link}" if link else "\n지도 주소는 서버 주소가 정해지면 알려 드릴게요."))


# ---------------------------------------------------------------------------
# picking a book (from buttons or typed titles)
# ---------------------------------------------------------------------------

def _ask_book(api, chat, mid, text: str, markup: dict | None, kind: str) -> None:
    """Ask which book (send or edit) and remember the open question for ``intake.CHOICE_TTL``.

    While it is open, photos go to holding instead of the possibly stale current book.
    """
    held = (intake.pending_choice() or {}).get("held", 0)
    if held:
        text += f"\n\n📥 사진 {held}장은 책을 고르면 거기에 붙일게요."
    res = _reply(api, chat, mid, text, markup)
    mid = mid or res.get("message_id")
    S.ui_set("pending_choice", {"at": S.iso(S.now_seoul()), "kind": kind, "chat_id": chat,
                                "message_id": mid, "text": text.split("\n\n📥 ")[0], "markup": markup,
                                "held": held})


def _resolve_into(api, chat, mid, slug: str, title: str) -> None:
    """Attach holding to a book and show it as one batch confirmation."""
    r = intake.resolve_holding(slug, title)
    S.ui_set("holding_msg", None)
    if r["status"] == "empty":
        _reply(api, chat, mid, "보류함이 이미 비어 있어요.")
        return
    if r["status"] == "duplicate":
        _reply(api, chat, mid, f"보류함 사진은 모두 이미 {_book(title)}에 있던 사진이라 건너뛰었어요.")
        return
    if r["status"] == "failed":
        _reply(api, chat, mid, "⚠️ 보류함 사진을 붙이지 못했어요. 사진은 보류함에 그대로 있어요.")
        return
    b = intake.get_batch(r["batch_id"])
    if mid:
        intake.set_batch_message(b["id"], chat, mid)
        b = intake.get_batch(b["id"])
    note = f"이제부터 사진은 {_book(title)}에 붙여요."
    if r.get("failed"):
        note += f"\n⚠️ {r['failed']}장은 붙이지 못해서 보류함에 남겨 두었어요."
    _render_batch(api, b, note=note, chat=chat)


def _apply_pick(api, chat, mid, purpose: str, slug: str, title: str, batch: str | None = None,
                new: bool = False) -> None:
    if new:
        intake.ensure_book(slug, title)
    title = intake.book_title(slug) or title
    if purpose == "hold":
        _resolve_into(api, chat, mid, slug, title)
    elif purpose == "move":
        old = intake.get_batch(batch or "")
        r = intake.move_batch(batch or "", slug, title)
        if old is None or r.get("reason") == "unknown_batch":
            _reply(api, chat, mid, "그 묶음은 이제 없어요.")
            return
        if not r.get("ok"):
            _reply(api, chat, mid, "⚠️ 사진을 옮기지 못했어요. 원래 책에 그대로 있어요.")
            return
        b = intake.get_batch(batch)
        note = f"🔁 {_book(old['title'])}에서 옮겨 왔어요."
        if r.get("current_switched"):
            note += f" 지금 읽는 책도 {_book(title)}{_ro(title)} 바꿨어요."
        if r.get("failed"):
            note += f"\n⚠️ {r['failed']}장은 옮기지 못해서 {_book(old['title'])}에 남겨 두었어요."
        same = (b.get("message") or {}).get("message_id") == mid
        _render_batch(api, b, note=note, chat=None)
        if not same:
            _reply(api, chat, mid, f"🔁 묶음 #{b['seq']} {r['moved']}장을 {_book(title)}{_ro(title)} 옮겼어요.")
    elif purpose == "learn":
        _learn_confirm(api, chat, mid, slug, title)
    else:
        pc = intake.pending_choice()
        S.ui_set("pending_choice", None)
        intake.set_current(slug, title)
        _reply(api, chat, mid, text_book_set(title, intake.book_count(slug)))
        n = intake.holding_count()
        if n and pc and pc.get("held"):  # photos sent while this question was open: CR just answered it
            _resolve_into(api, chat, None, slug, title)
        elif n:
            rows = [[("네, 붙여요", {"a": "pick", "slug": slug, "title": title, "for": "hold"}),
                     ("아니요, 그대로 둘게요", {"a": "cancel"})]]
            S.ui_set("holding_msg", None)
            api.send_message(chat, f"📥 보류함에 사진 {n}장이 있어요. 이것도 {_book(title)}에 붙일까요?", _kb(rows))


def _on_title(api, chat, text: str) -> None:
    waiting = S.ui_get("awaiting_title")
    S.ui_set("awaiting_title", None)
    at = S.parse((waiting or {}).get("at"))
    if waiting and (at is None or S.now_seoul() - at > intake.CHOICE_TTL):
        waiting = None  # a title wait older than 10 minutes is forgotten
    purpose = (waiting or {}).get("for", "set")
    batch = (waiting or {}).get("batch")
    m = intake.match_title(text)
    if not m["slug"]:
        api.send_message(chat, "제목을 알아보지 못했어요. 책 제목을 글자로 보내 주세요.")
        return
    if m["kind"] == "exact":
        _apply_pick(api, chat, None, purpose, m["slug"], m["title"], batch)
        return
    new_pick = {"a": "pick", "slug": m["slug"], "title": m["title"], "for": purpose, "batch": batch, "new": True}
    if m["kind"] == "similar":
        rows = [[(f"{_book(_short(c['title']))} 맞아요",
                  {"a": "pick", "slug": c["slug"], "title": c["title"], "for": purpose, "batch": batch})]
                for c in m["candidates"]]
        rows += [[(f"새 책 {_book(_short(m['title']))}", new_pick)], [("취소", {"a": "cancel"})]]
        _ask(api, chat, purpose, "📚 서재에 비슷한 책이 있어요. 같은 책인가요?", _kb(rows), "similar")
    elif waiting:
        _apply_pick(api, chat, None, purpose, m["slug"], m["title"], batch, new=True)
    else:
        rows = [[("새 책으로 만들기", new_pick)], [("취소", {"a": "cancel"})]]
        _ask(api, chat, purpose, f"📚 {_book(m['title'])}, 처음 보는 책이에요. 새 책으로 만들까요?",
             _kb(rows), "new")


def _ask(api, chat, purpose: str, text: str, markup: dict, kind: str) -> None:
    """A question about the reading book holds photos; other questions (move, learn) do not."""
    if purpose == "set":
        _ask_book(api, chat, None, text, markup, kind)
    else:
        api.send_message(chat, text, markup)


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------

def _menu_move(api, chat, mid=None, batch_id: str | None = None) -> None:
    batches = intake.recent_batches(3)
    b = intake.get_batch(batch_id) if batch_id else (batches[0] if batches else None)
    if b is None:
        _reply(api, chat, mid, "옮길 묶음이 없어요.")
        return
    markup = _picker("move", batch=b["id"], exclude=b["slug"])
    others = [x for x in batches if x["id"] != b["id"]]
    if others:
        extra = _kb([[(f"대신 묶음 #{x['seq']} 옮기기", {"a": "mv", "batch": x["id"]})] for x in others])
        markup = {"inline_keyboard": markup["inline_keyboard"] + extra["inline_keyboard"]}
    _reply(api, chat, mid, f"🔁 {_batch_label(b)}을 어느 책으로 옮길까요?", markup)


def _menu_delete(api, chat, mid=None, batch_id: str | None = None) -> None:
    batches = intake.recent_batches(3)
    b = intake.get_batch(batch_id) if batch_id else (batches[0] if batches else None)
    if b is None:
        _reply(api, chat, mid, "지울 묶음이 없어요.")
        return
    rows = [[("🗑 네, 지워요", {"a": "delok", "batch": b["id"]}), ("아니요", {"a": "keep", "batch": b["id"]})]]
    rows += [[(f"대신 묶음 #{x['seq']} 지우기", {"a": "del", "batch": x["id"]})]
             for x in batches if x["id"] != b["id"]]
    _reply(api, chat, mid, f"🗑 {_batch_label(b)}을 지울까요? 사진과 읽은 글이 함께 지워져요.", _kb(rows))


def _menu_now(api, chat) -> None:
    cur = intake.current()
    if cur:
        api.send_message(chat, text_book_set(cur["title"], intake.book_count(cur["slug"])))
    else:
        _ask_book(api, chat, None, "📖 지금 정해진 책이 없어요. 사진을 보내기 전에 책을 골라 주세요.",
                  _picker("set"), "picker")


def _menu_learn(api, chat) -> None:
    cur = intake.current()
    if cur:
        _learn_confirm(api, chat, None, cur["slug"], cur["title"])
    else:
        api.send_message(chat, "🧠 어느 책에서 배울까요?", _picker("learn"))


def _menu_status(api, chat) -> None:
    s = intake.summary()
    lines = ["📊 서재 현황"]
    lines += [f"{_book(b['title'])} {b['count']}장" for b in s["books"][:15]] or ["아직 책이 없어요."]
    lines.append(f"\n읽기 대기 {s['ocr_pending']}장 · 분류 대기 {s['unclassified']}개 · 보류함 {s['holding']}장")
    api.send_message(chat, "\n".join(lines))


def _command(text: str) -> tuple[str, str]:
    if not text.startswith("/"):
        return text, ""
    head, _, arg = text.partition(" ")
    return head.split("@", 1)[0].lower(), arg.strip()


def _on_text(api, chat, text: str) -> None:
    cmd, arg = _command(text)
    simple = {
        MENU_NOW: _menu_now, "/now": _menu_now, MENU_LEARN: _menu_learn, "/learn": _menu_learn,
        MENU_STATUS: _menu_status, "/status": _menu_status,
        MENU_MOVE: _menu_move, "/move": _menu_move, MENU_DELETE: _menu_delete, "/undo": _menu_delete,
    }
    if cmd in simple or cmd in (MENU_BOOK, "/book", "/start", "/help"):
        S.ui_set("awaiting_title", None)
    if cmd in simple:
        simple[cmd](api, chat)
    elif cmd in (MENU_BOOK, "/book"):
        if arg:
            _on_title(api, chat, arg)
        else:
            _ask_book(api, chat, None, "📚 어느 책을 읽고 있어요?", _picker("set"), "picker")
    elif cmd == "/start":
        api.send_message(chat, "🌙 안녕하세요, Clair예요. 책 제목을 보내고 밑줄 친 쪽 사진을 보내 주세요. "
                               "아래 메뉴 버튼으로 언제든 책을 고를 수 있어요.", keyboards.main_menu())
    elif cmd == "/help":
        api.send_message(chat, text_help(), keyboards.main_menu())
    elif cmd.startswith("/"):
        api.send_message(chat, "그 명령은 몰라요. /help 를 눌러 보세요.")
    else:
        _on_title(api, chat, text)


def _image_doc(doc: dict | None) -> bool:
    return bool(doc) and str(doc.get("mime_type", "")).startswith("image/")


def _render_held(api, chat) -> None:
    """A held photo: add a line to the open book question, or ask the holding question."""
    pc = intake.pending_choice()
    if not (pc and pc.get("message_id")):
        _render_holding(api, chat)
        return
    n = intake.holding_count()
    api.edit_message_text(pc["chat_id"], pc["message_id"],
                          f"{pc['text']}\n\n📥 사진 {n}장은 책을 고르면 거기에 붙일게요.",
                          reply_markup=pc.get("markup"))
    S.ui_set("pending_choice", {**pc, "held": n})


def _render_duplicate(api, chat, slug: str) -> None:
    """All-duplicate photos open no batch; one short note, its count edited for 90 seconds."""
    now = S.now_seoul()
    slot = S.ui_get("dupe_msg")
    at = S.parse((slot or {}).get("at"))
    title = intake.book_title(slug)
    if slot and slot.get("slug") == slug and at and now - at <= intake.BATCH_GAP:
        n = slot["n"] + 1
        api.edit_message_text(slot["chat_id"], slot["message_id"],
                              f"같은 사진이 이미 {_book(title)}에 있어서 {n}장 건너뛰었어요.")
        S.ui_set("dupe_msg", {**slot, "n": n, "at": S.iso(now)})
        return
    res = api.send_message(chat, f"같은 사진이 이미 {_book(title)}에 있어서 1장 건너뛰었어요.")
    S.ui_set("dupe_msg", {"chat_id": chat, "message_id": res.get("message_id"), "slug": slug, "n": 1,
                          "at": S.iso(now)})


def _on_photo(api, chat, msg: dict) -> None:
    if msg.get("photo"):
        item, fname, mime = msg["photo"][-1], "", "image/jpeg"
    else:
        item = msg["document"]
        fname, mime = item.get("file_name") or "", item.get("mime_type") or ""
    if (item.get("file_size") or 0) > MAX_FILE_BYTES:  # Bot API getFile limit
        api.send_message(chat, "📎 이 파일은 20MB가 넘어서 받을 수 없어요. "
                               "사진으로 보내 주시거나 조금 줄여서 보내 주세요.")
        return
    data, path_name, guessed = api.get_file(item["file_id"])  # download outside the lock
    with _UI_LOCK:
        r = intake.add_photo(data, fname or path_name, mime or guessed, caption=msg.get("caption") or "",
                             media_group_id=msg.get("media_group_id"))
        if r["status"] == "held":
            _render_held(api, chat)
        elif r["status"] == "duplicate":
            _render_duplicate(api, chat, r["slug"])
        else:
            _render_batch(api, intake.get_batch(r["batch_id"]), chat=chat)


def _on_message(api, msg: dict) -> None:
    chat = msg["chat"]["id"]
    if msg.get("photo") or _image_doc(msg.get("document")):
        _on_photo(api, chat, msg)
        return
    with _UI_LOCK:
        if msg.get("document"):
            api.send_message(chat, "이 파일은 사진이 아니라서 아직 못 받아요. 책 사진(jpg·png)으로 보내 주세요.")
        elif (msg.get("text") or "").strip():
            _on_text(api, chat, msg["text"].strip())


# ---------------------------------------------------------------------------
# callbacks
# ---------------------------------------------------------------------------

def _on_callback(api, cq: dict) -> None:
    p = S.button(cq.get("data") or "")
    chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
    mid = (cq.get("message") or {}).get("message_id")
    batch = intake.get_batch(p["batch"]) if p and p.get("batch") else None
    needs_batch = p and p.get("a") in ("ok", "mv", "del", "delok", "keep")
    if p is None or chat is None or (needs_batch and batch is None):
        api.answer_callback_query(cq.get("id"), text=EXPIRED)
        return
    a = p["a"]
    api.answer_callback_query(cq.get("id"))
    if a in ("pick", "newbook", "cancel", "delok", "learn", "hold_drop_ok"):
        S.consume_group(p["g"])  # one-shot choices
    if a == "pick":
        _apply_pick(api, chat, mid, p["for"], p["slug"], p["title"], p.get("batch"), new=bool(p.get("new")))
    elif a == "newbook":
        S.ui_set("awaiting_title", {"for": p["for"], "batch": p.get("batch"), "at": S.iso(S.now_seoul())})
        if p["for"] == "set":
            _ask_book(api, chat, mid, "✏️ 새 책 제목을 글로 보내 주세요.", None, "title")
        else:
            _reply(api, chat, mid, "✏️ 새 책 제목을 글로 보내 주세요.")
    elif a == "more":
        S.consume_group(p["g"])
        markup = _picker(p["for"], p.get("batch"), p["off"], p.get("exclude"))
        if p["for"] == "set":
            _ask_book(api, chat, mid, "📚 다른 책들이에요.", markup, "picker")
        else:
            _reply(api, chat, mid, "📚 다른 책들이에요.", markup)
    elif a == "cancel":
        S.ui_set("awaiting_title", None)
        pc = intake.pending_choice()
        S.ui_set("pending_choice", None)
        _reply(api, chat, mid, "알겠어요, 그대로 둘게요.")
        if pc and intake.holding_count():  # photos waited for this answer: ask where they go
            S.ui_set("holding_msg", None)
            _render_holding(api, chat)
    elif a == "ok":
        intake.confirm_batch(batch["id"])
        _render_batch(api, intake.get_batch(batch["id"]))
    elif a == "mv":
        _menu_move(api, chat, mid, batch["id"])
    elif a == "del":
        _menu_delete(api, chat, mid, batch["id"])
    elif a == "keep":
        if (batch.get("message") or {}).get("message_id") == mid:
            _render_batch(api, batch)
        else:
            _reply(api, chat, mid, "알겠어요, 그대로 둘게요.")
    elif a == "delok":
        r = intake.delete_batch(batch["id"])
        text = f"🗑 묶음 #{r['seq']} 사진 {r['deleted']}장을 지웠어요."
        bm = batch.get("message") or {}
        if bm.get("message_id") and bm.get("message_id") != mid:
            api.edit_message_text(bm["chat_id"], bm["message_id"], text)
        _reply(api, chat, mid, text)
    elif a == "hold_drop":
        n = intake.holding_count()
        rows = [[("🗑 네, 버려요", {"a": "hold_drop_ok"}), ("아니요", {"a": "hold_back"})]]
        _reply(api, chat, mid, f"🗑 보류함 사진 {n}장을 버릴까요? 어디에도 저장되지 않아요.", _kb(rows))
    elif a == "hold_drop_ok":
        n = intake.discard_holding()
        S.ui_set("holding_msg", None)
        _reply(api, chat, mid, f"🗑 보류함 사진 {n}장을 버렸어요.")
    elif a == "hold_back":
        S.consume_group(p["g"])
        _render_holding(api, chat, mid)
    elif a == "learn":
        _start_learn(api, chat, mid, p["title"], int(p["days"]))


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def _chat_of(update: dict):
    msg = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    return (msg.get("chat") or {}).get("id")


def handle_update(update: dict, api: TelegramAPI) -> None:
    """Process one Telegram update. Unknown senders and re-delivered updates are ignored silently."""
    allowed = get_settings().telegram_allowed_user_id
    msg, cq = update.get("message"), update.get("callback_query")
    sender = ((msg or cq or {}).get("from") or {}).get("id")
    if not allowed or sender != allowed:
        return
    if not S.mark_update(update.get("update_id")):
        return
    try:
        if cq:
            with _UI_LOCK:
                _on_callback(api, cq)
        elif msg:
            _on_message(api, msg)
    except Exception:  # noqa: BLE001 - a webhook thread must never die loudly
        log.exception("텔레그램 업데이트 처리 실패")
        chat = _chat_of(update)
        if chat is not None:
            try:
                api.send_message(chat, "⚠️ 앗, 처리하다 오류가 났어요. 잠시 뒤에 한 번만 다시 보내 주세요. "
                                       "같은 사진은 두 번 저장되지 않아요.")
            except Exception:  # noqa: BLE001
                pass
