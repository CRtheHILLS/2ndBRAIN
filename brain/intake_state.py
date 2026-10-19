"""Persistent state for the Telegram book intake (``DATA_DIR/telegram/state.json``).

One module-level re-entrant lock serializes every mutation (single server
instance); writes are atomic (tmp file + ``os.replace``) so a crash never
leaves a half-written state behind.
"""

import datetime as dt
import json
import logging
import os
import re
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

from . import catalog, graph, store
from .config import get_settings

SEOUL = ZoneInfo("Asia/Seoul")
log = logging.getLogger("brain.intake")
LOCK = threading.RLock()

MAX_BATCHES = 10
MAX_SEEN = 500
MAX_BUTTONS = 300
MAX_ALBUMS = 20
LEARN_GRACE = dt.timedelta(minutes=30)  # Telegram files wait this long before auto-classification


def now_seoul() -> dt.datetime:
    return dt.datetime.now(SEOUL)


def learn_hold_until() -> str:
    """``catalog.register(hold_until=…)`` value: local naive ISO seconds, like ``catalog`` compares."""
    return (dt.datetime.now() + LEARN_GRACE).isoformat(timespec="seconds")


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


def _markup_keys(markup) -> set[str]:
    if not isinstance(markup, dict):
        return set()
    rows = markup.get("inline_keyboard") or []
    return {b["callback_data"][2:] for row in rows for b in row
            if str(b.get("callback_data", "")).startswith("k:")}


def _live_keys(st: dict) -> set[str]:
    out: set[str] = set()
    for b in st["batches"]:
        out |= _markup_keys(b.get("kb"))
    for slot in st["ui"].values():
        if isinstance(slot, dict):
            out |= _markup_keys(slot.get("markup"))
    return out


def save(st: dict) -> None:
    st["batches"] = st["batches"][-MAX_BATCHES:]
    st["seen_update_ids"] = st["seen_update_ids"][-MAX_SEEN:]
    if len(st["buttons"]) > MAX_BUTTONS:
        live = _live_keys(st)  # keyboards still on screen (batch confirmations, open questions)
        keys = sorted(st["buttons"], key=lambda k: int(k))
        keep = set(keys[-MAX_BUTTONS:]) | live
        st["buttons"] = {k: v for k, v in st["buttons"].items() if k in keep}
    if len(st["albums"]) > MAX_ALBUMS:
        st["albums"] = dict(list(st["albums"].items())[-MAX_ALBUMS:])
    p = state_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, p)


@contextmanager
def edit(save_on_error: bool = False):
    """``with edit() as st:`` — load under the lock, save on clean exit.

    ``save_on_error=True`` also saves when the body raises, for multi-step file work that
    updates the state as it goes (so disk and state never disagree).
    """
    with LOCK:
        st = load()
        try:
            yield st
        except BaseException:
            if save_on_error:
                save(st)
            raise
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


_UNDERLINE = re.compile(r"==(.+?)==", re.S)


def underlines(body: str) -> list[str]:
    """``==밑줄==`` spans of an OCR body, ``==`` stripped, whitespace collapsed, blanks dropped."""
    return [" ".join(m.split()) for m in _UNDERLINE.findall(body or "") if m.strip()]


def ui_get(key: str, default=None):
    with LOCK:
        return load()["ui"].get(key, default)


def ui_set(key: str, value) -> None:
    with edit() as st:
        if value is None:
            st["ui"].pop(key, None)
        else:
            st["ui"][key] = value


# ---------------------------------------------------------------------------
# file / hook helpers for move & delete (used by intake)
# ---------------------------------------------------------------------------

def forget_file(slug: str, filename: str) -> None:
    """Drop one file from catalog / graph / OCR queue (hooks are added by Task 3 and ocr.py)."""
    forget = getattr(catalog, "forget", None)
    if forget:
        forget(slug, filename)
    remove_node = getattr(graph, "remove_node", None)
    if remove_node:
        remove_node("src:" + catalog.make_id(slug, filename)[:16])


def ocr_module():
    try:
        from . import ocr  # noqa: PLC0415 - optional until Task 1 lands
        return ocr
    except ImportError:
        return None


def take_ocr_pending(slug: str, filename: str) -> dict | None:
    ocr = ocr_module()
    lister = getattr(ocr, "list_pending", None) if ocr else None
    if not lister:
        return None
    eid = catalog.make_id(slug, filename)
    entry = next((e for e in lister() if e.get("id") == eid), None)
    if entry and getattr(ocr, "remove_pending", None):
        ocr.remove_pending(eid)
    return entry


def move_files(f: dict, src_dir: Path, dst_dir: Path, new_slug: str) -> None:
    """Move one photo's original + md; on failure put back what was already moved and re-raise."""
    img, md = src_dir / f["file"], src_dir / f["md"]
    new_img, new_md = dst_dir / f["file"], dst_dir / f["md"]
    try:
        if img.is_file():
            shutil.move(str(img), str(new_img))
        if md.is_file():
            meta, body = store.read_md(md)
            meta["book"] = new_slug
            store.write_md(new_md, meta, body)
            md.unlink()
    except Exception:
        if new_img.is_file() and not img.exists():
            shutil.move(str(new_img), str(img))
        if new_md.is_file() and md.is_file():
            new_md.unlink()
        raise


def rehome(old: str, new_slug: str, f: dict, dst_dir: Path) -> None:
    """Catalog / graph / OCR-queue bookkeeping after a successful file move (never raises)."""
    try:
        pend = take_ocr_pending(old, f["file"])
        forget_file(old, f["file"])
        new_md, new_img = dst_dir / f["md"], dst_dir / f["file"]
        if new_md.is_file():
            catalog.register(new_slug, f["file"], new_md, f["sha256"], hold_until=learn_hold_until())
        ocr = ocr_module()
        if pend and ocr and getattr(ocr, "add_pending", None):
            ocr.add_pending({**pend, "id": catalog.make_id(new_slug, f["file"]), "book": new_slug,
                             "path": str(new_md), "image": str(new_img)})
    except Exception as e:  # noqa: BLE001 - the files already moved; state must say so
        log.warning("옮긴 사진 재등록 실패(파일은 옮겨짐): %s", e)
