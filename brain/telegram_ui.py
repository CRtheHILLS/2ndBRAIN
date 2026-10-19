"""Telegram bot copy and keyboards (pure): menu labels, Korean particles, message texts.

Everything here is side-effect free so it is easy to test; ``telegram_bot`` does the I/O.
"""

from . import intake_state as S
from .config import get_settings

MENU_BOOK, MENU_NOW, MENU_MOVE = "📚 책 고르기", "📖 지금 책", "🔁 방금 묶음 옮기기"
MENU_DELETE, MENU_LEARN, MENU_STATUS = "🗑 방금 묶음 지우기", "🧠 이 책에서 배우기", "📊 서재 현황"
MENU = [[MENU_BOOK, MENU_NOW], [MENU_MOVE, MENU_DELETE], [MENU_LEARN, MENU_STATUS]]
COMMANDS = [
    ("start", "시작하기"), ("book", "책 고르기"), ("now", "지금 읽는 책 보기"),
    ("move", "방금 묶음 다른 책으로 옮기기"), ("undo", "방금 묶음 지우기"),
    ("learn", "이 책에서 배우기"), ("status", "서재 현황"), ("help", "사용법"),
]
EXPIRED = "만료됐어요"
MAX_UNDERLINES = 10


# ---------------------------------------------------------------------------
# keyboards
# ---------------------------------------------------------------------------

class keyboards:  # noqa: N801 - a namespace of pure functions
    @staticmethod
    def main_menu() -> dict:
        rows = [[t for t in row if t != MENU_LEARN or get_settings().telegram_learn_button] for row in MENU]
        return {"keyboard": [[{"text": t} for t in row] for row in rows if row],
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


def text_batch(b: dict, total: int, note: str = "") -> str:
    """The one confirmation message of a batch (OCR results follow in their own notice)."""
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


underlines = S.underlines  # ``==밑줄==`` spans of an OCR body


def text_ocr_done(done: int, marks: int) -> str:
    return f"✍️ {done}장 읽었어요 · 밑줄 {marks}군데"


LEARN_HIDDEN = "이 기능은 나중에 열어요. 지금은 사진 업로드만 해요."


def commands() -> list[tuple[str, str]]:
    on = get_settings().telegram_learn_button
    return [c for c in COMMANDS if on or c[0] != "learn"]


def text_ocr_pending(waiting: int, n: int = 1) -> str:
    if get_settings().ocr_mode == "clair":
        return f"📦 사진 {n}장 보관했어요. 글자와 밑줄·표시는 Clair가 읽을게요."
    return f"📦 사진은 안전하게 보관했어요. 글자는 Clair가 다음 세션에서 읽을게요. (읽기 대기 {waiting}장)"


def text_ocr_notice(done: int, marks: int, pending: int, waiting: int) -> list[str]:
    """Messages to send after a batch was read: done line and/or pending line."""
    out = []
    if done:
        out.append(text_ocr_done(done, marks))
    if pending:
        out.append(text_ocr_pending(max(waiting, pending), pending))
    return out


def text_underlines(marks: list[str]) -> str:
    if not marks:
        return "📝 이 묶음에는 밑줄 친 곳을 찾지 못했어요."
    shown = "\n".join(f"• {m}" for m in marks[:MAX_UNDERLINES])
    return f"📝 밑줄 친 곳이에요\n{shown}\n(총 {len(marks)}군데)"


def text_clair_read(title: str, marks: int) -> str:
    return f"✍️ {_book(title)} 사진 1장을 Clair가 읽었어요 · 밑줄 {marks}군데"


def text_holding_warning(n: int) -> str:
    return f"⏳ 보류 중인 사진 {n}장이 1시간 뒤 지워져요. 어느 책인지 골라 주세요."


def text_help() -> str:
    return ("📖 이렇게 쓰면 돼요\n"
            "1. 책 제목을 글로 보내면 '지금 읽는 책'이 돼요.\n"
            "2. 밑줄 친 쪽 사진을 보내면 그 책에 붙여요. 여러 장을 한꺼번에 보내도 돼요.\n"
            "3. 사진 설명 첫 줄에 책 제목을 쓰면 그 사진만 그 책으로 가요. "
            "p.123 이나 123쪽은 쪽수, 3장은 장, #단어는 태그로 적어 둘게요.\n"
            "4. 6시간이 지나거나 날짜가 바뀌면 사진을 보류함에 두고 어느 책인지 먼저 물어볼게요.\n"
            "5. 잘못 붙었으면 🔁 옮기기나 🗑 지우기를 눌러 주세요.\n"
            "사진을 '파일'로 보내면 원본 화질이라 글자를 더 잘 읽어요.")
