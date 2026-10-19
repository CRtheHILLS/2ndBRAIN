"""Persistent state for the Telegram book intake (``DATA_DIR/telegram/state.json``).

One module-level re-entrant lock serializes every mutation (single server
instance); writes are atomic (tmp file + ``os.replace``) so a crash never
leaves a half-written state behind.
"""

import datetime as dt
import json
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import get_settings

SEOUL = ZoneInfo("Asia/Seoul")
LOCK = threading.RLock()

MAX_BATCHES = 10
MAX_SEEN = 500
MAX_BUTTONS = 300
MAX_ALBUMS = 20


def now_seoul() -> dt.datetime:
    return dt.datetime.now(SEOUL)


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def parse(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=SEOUL)


def telegram_dir() -> Path:
    p = get_settings().data_dir / "telegram"
    p.mkdir(parents=True, exist_ok=True)
    return p


def holding_dir() -> Path:
    p = telegram_dir() / "holding"
    p.mkdir(parents=True, exist_ok=True)
    return p


def state_path() -> Path:
    return telegram_dir() / "state.json"


def _empty() -> dict:
    return {
        "current_book": None, "recent_books": [], "holding": [], "batches": [],
        "batch_seq": 0, "seen_update_ids": [], "buttons": {}, "button_seq": 0,
        "albums": {}, "ui": {},
    }


def load() -> dict:
    p = state_path()
    st = _empty()
    if p.is_file():
        try:
            d = json.loads(p.read_text("utf-8"))
            if isinstance(d, dict):
                st.update(d)
        except (json.JSONDecodeError, OSError):
            pass
    return st


def save(st: dict) -> None:
    st["batches"] = st["batches"][-MAX_BATCHES:]
    st["seen_update_ids"] = st["seen_update_ids"][-MAX_SEEN:]
    if len(st["buttons"]) > MAX_BUTTONS:
        keys = sorted(st["buttons"], key=lambda k: int(k))
        st["buttons"] = {k: st["buttons"][k] for k in keys[-MAX_BUTTONS:]}
    if len(st["albums"]) > MAX_ALBUMS:
        st["albums"] = dict(list(st["albums"].items())[-MAX_ALBUMS:])
    p = state_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, p)


@contextmanager
def edit():
    """``with edit() as st:`` — load under the lock, save on clean exit."""
    with LOCK:
        st = load()
        yield st
        save(st)


# ---------------------------------------------------------------------------
# small shared helpers (update ids, inline-button keys, ui slots)
# ---------------------------------------------------------------------------

def mark_update(update_id) -> bool:
    """True the first time an ``update_id`` is seen, False for a re-delivery."""
    if update_id is None:
        return True
    with edit() as st:
        if update_id in st["seen_update_ids"]:
            return False
        st["seen_update_ids"].append(update_id)
        return True


def register_buttons(payloads: list[dict]) -> list[str]:
    """Store payloads under short numeric keys (one group per keyboard); returns ``k:<n>`` data."""
    with edit() as st:
        st["button_seq"] += 1
        group = st["button_seq"]
        out = []
        for p in payloads:
            st["button_seq"] += 1
            key = str(st["button_seq"])
            st["buttons"][key] = {**p, "g": group}
            out.append(f"k:{key}")
        return out


def button(data: str) -> dict | None:
    if not data or not data.startswith("k:"):
        return None
    with LOCK:
        return load()["buttons"].get(data[2:])


def consume_group(group) -> None:
    """Expire every button of one keyboard (one-shot choices)."""
    with edit() as st:
        st["buttons"] = {k: v for k, v in st["buttons"].items() if v.get("g") != group}


_PAGE = re.compile(r"(?<![A-Za-z])[pP]\.\s*(\d+)|(\d+)\s*쪽")
_CHAPTER = re.compile(r"#?(\d+)\s*장")
_TAG = re.compile(r"#([^\s#]+)")


def parse_caption(caption: str) -> dict:
    """Caption → ``{"title", "page", "chapter", "tags", "rest", "note"}``.

    ``title`` is the first remaining line (may be ''); ``rest`` is everything after it and
    ``note`` is all remaining text (used when the first line is not a known book).
    """
    text = caption or ""
    page = chapter = None
    m = _PAGE.search(text)
    if m:
        page = int(m.group(1) or m.group(2))
        text = text[:m.start()] + text[m.end():]
    m = _CHAPTER.search(text)
    if m:
        chapter = int(m.group(1))
        text = text[:m.start()] + text[m.end():]
    tags = _TAG.findall(text)
    text = _TAG.sub("", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return {"title": lines[0] if lines else "", "page": page, "chapter": chapter, "tags": tags,
            "rest": "\n".join(lines[1:]), "note": "\n".join(lines)}


def ui_get(key: str, default=None):
    with LOCK:
        return load()["ui"].get(key, default)


def ui_set(key: str, value) -> None:
    with edit() as st:
        if value is None:
            st["ui"].pop(key, None)
        else:
            st["ui"][key] = value
