"""Telegram book intake: which book a photo belongs to, batches, holding, move/delete.

The one rule that matters: a photo never lands in the wrong book.  A photo
goes to (1) the book its caption names (>= 0.9 match, that photo/album only),
else (2) the current book while it is fresh (6 h since last activity, same
Seoul date), else (3) the holding area until CR picks a book with a button.

State lives in ``intake_state`` (atomic json + one process lock).
"""

import datetime as dt
import difflib
import hashlib
import logging
from pathlib import Path

from . import catalog, index, ingest, store
from . import marks as M
from . import intake_state as S
from .config import get_settings
from .slug import slugify

EXPIRY = dt.timedelta(hours=6)
BATCH_GAP = dt.timedelta(seconds=90)
BATCH_MAX_AGE = dt.timedelta(minutes=10)
LEARN_GRACE = S.LEARN_GRACE
learn_hold_until = S.learn_hold_until
CHOICE_TTL = dt.timedelta(minutes=10)  # an unanswered book question / title wait expires
SUGGEST_RATIO = 0.8
CAPTION_RATIO = 0.9

log = logging.getLogger(__name__)

MIME_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
            "image/heic": ".heic", "image/heif": ".heif"}


class State:
    """Load/save of ``DATA_DIR/telegram/state.json`` (see ``intake_state``)."""
    path = staticmethod(S.state_path)
    load = staticmethod(S.load)
    save = staticmethod(S.save)


def _now(now: dt.datetime | None) -> dt.datetime:
    if now is None:
        return S.now_seoul()
    return now if now.tzinfo else now.replace(tzinfo=S.SEOUL)


# ---------------------------------------------------------------------------
# titles
# ---------------------------------------------------------------------------

def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _scored(title: str) -> list[tuple[float, dict]]:
    s = slugify(title)
    t = title.strip().lower()
    out = []
    for b in store.list_books():
        score = 1.0 if s and b["slug"] == s else max(
            _ratio(t, str(b.get("title", "")).strip().lower()), _ratio(s, b["slug"]))
        out.append((score, b))
    return sorted(out, key=lambda x: -x[0])


def match_title(title: str) -> dict:
    """``exact`` (same slug) / ``similar`` (>= 0.8 on title or slug) / ``new``."""
    title = title.strip()
    s = slugify(title)
    scored = _scored(title)
    if scored and scored[0][0] >= 1.0:
        b = scored[0][1]
        return {"kind": "exact", "slug": b["slug"], "title": b.get("title") or b["slug"], "candidates": []}
    cands = [{"slug": b["slug"], "title": b.get("title") or b["slug"], "score": round(sc, 3)}
             for sc, b in scored if sc >= SUGGEST_RATIO][:3]
    if cands:
        return {"kind": "similar", "slug": s, "title": title, "candidates": cands}
    return {"kind": "new", "slug": s, "title": title, "candidates": []}


def book_title(slug: str) -> str:
    for b in store.list_books():
        if b["slug"] == slug:
            return b.get("title") or slug
    return slug


def ensure_book(slug: str, title: str) -> None:
    """Create a book only when it does not exist (never overwrite a title)."""
    if not any(b["slug"] == slug for b in store.list_books()):
        store.upsert_book(slug, title)


def book_count(slug: str) -> int:
    d = get_settings().data_dir / "books" / slug / "raw"
    return len(list(d.glob("*.md"))) if d.is_dir() else 0


# ---------------------------------------------------------------------------
# current book
# ---------------------------------------------------------------------------

def _touch_recent(st: dict, slug: str, title: str, now: dt.datetime) -> None:
    st["recent_books"] = [{"slug": slug, "title": title, "at": S.iso(now)}] + [
        r for r in st["recent_books"] if r["slug"] != slug][:19]


def set_current(slug: str, title: str, now: dt.datetime | None = None) -> dict:
    now = _now(now)
    with S.edit() as st:
        st["current_book"] = {"slug": slug, "title": title, "set_at": S.iso(now), "last_at": S.iso(now)}
        _touch_recent(st, slug, title, now)
        return dict(st["current_book"])


def _fresh(cb: dict | None, now: dt.datetime) -> bool:
    if not cb:
        return False
    last = max(S.parse(cb.get("set_at")), S.parse(cb.get("last_at") or cb.get("set_at")))
    return now - last <= EXPIRY and now.astimezone(S.SEOUL).date() == last.astimezone(S.SEOUL).date()


def current(now: dt.datetime | None = None) -> dict | None:
    """The current book, or None after 6 h of no activity or a Seoul date change."""
    now = _now(now)
    with S.LOCK:
        cb = S.load()["current_book"]
    return dict(cb) if _fresh(cb, now) else None


def last_book() -> dict | None:
    """The most recent current book even if it has expired (for the holding question)."""
    with S.LOCK:
        cb = S.load()["current_book"]
    return dict(cb) if cb else None


def recent_books(n: int = 6, offset: int = 0) -> list[dict]:
    """Recently used books first, then the rest of the shelf by latest upload."""
    with S.LOCK:
        recent = S.load()["recent_books"]
    books = {b["slug"]: b for b in store.list_books()}
    out = [{"slug": r["slug"], "title": books[r["slug"]].get("title") or r["slug"]}
           for r in recent if r["slug"] in books]
    seen = {b["slug"] for b in out}

    def mtime(slug):
        d = get_settings().data_dir / "books" / slug / "raw"
        return d.stat().st_mtime if d.is_dir() else 0.0

    rest = sorted((b for b in books.values() if b["slug"] not in seen), key=lambda b: -mtime(b["slug"]))
    out += [{"slug": b["slug"], "title": b.get("title") or b["slug"]} for b in rest]
    return out[offset:offset + n]


# ---------------------------------------------------------------------------
# captions
# ---------------------------------------------------------------------------

parse_caption = S.parse_caption  # pure helper, lives in intake_state to keep this module small


def _caption_book(title: str) -> dict | None:
    if not title:
        return None
    scored = _scored(title)
    if scored and scored[0][0] >= CAPTION_RATIO:
        b = scored[0][1]
        return {"slug": b["slug"], "title": b.get("title") or b["slug"]}
    return None


def _caption_meta(caption: str) -> tuple[dict | None, dict]:
    """(override book or None, meta {page, chapter, tags, note})."""
    c = parse_caption(caption)
    book = _caption_book(c["title"])
    note = c["rest"] if book else c["note"]
    return book, {"page": c["page"], "chapter": c["chapter"], "tags": c["tags"], "note": note}


# ---------------------------------------------------------------------------
# photos
# ---------------------------------------------------------------------------

def _known_shas(slug: str) -> set[str]:
    d = get_settings().data_dir / "books" / slug / "raw"
    out = set()
    for p in d.glob("*.md") if d.is_dir() else ():
        try:
            sha = store.read_md(p)[0].get("sha256")
        except (OSError, ValueError):
            continue
        if sha:
            out.add(str(sha))
    return out


def _ext(filename: str, mime: str) -> str:
    ext = Path(filename or "").suffix.lower()
    return ext if ext in ingest.IMG else MIME_EXT.get(mime or "", ".jpg")


def _new_batch(st: dict, slug: str, title: str, now: dt.datetime, *, via_current: bool,
               mgid: str | None) -> dict:
    st["batch_seq"] += 1
    b = {"id": f"b{now.strftime('%Y%m%d-%H%M%S')}-{st['batch_seq']}", "seq": st["batch_seq"],
         "slug": slug, "title": title, "files": [], "dupes": 0, "created_at": S.iso(now),
         "last_at": S.iso(now), "media_groups": [mgid] if mgid else [], "confirmed": False,
         "learned_hold_until": S.iso(now + LEARN_GRACE), "via_current": via_current,
         "message": None}
    st["batches"].append(b)
    return b


def _pick_batch(st: dict, slug: str, now: dt.datetime, mgid: str | None) -> dict | None:
    for b in reversed(st["batches"]):
        if mgid and mgid in b["media_groups"] and b["slug"] == slug:
            return b
    if st["batches"]:
        b = st["batches"][-1]
        if (b["slug"] == slug and now - S.parse(b["last_at"]) <= BATCH_GAP
                and now - S.parse(b["created_at"]) <= BATCH_MAX_AGE):
            if mgid and mgid not in b["media_groups"]:
                b["media_groups"].append(mgid)
            return b
    return None


def _ocr_state(md: Path) -> str:
    try:
        return str(store.read_md(md)[0].get("ocr") or "done")
    except (OSError, ValueError):
        return "done"


def _attach(st: dict, b: dict, data: bytes, ext: str, meta: dict, now: dt.datetime) -> str | None:
    """Store one photo in batch ``b``; returns its ocr state, or None for a duplicate."""
    sha = hashlib.sha256(data).hexdigest()
    if sha in _known_shas(b["slug"]):
        b["dupes"] += 1
        return None
    filename = f"tg-{b['id']}-{len(b['files']) + b['dupes'] + 1}{ext}"
    extra = {"via": "telegram", "batch": b["id"], "uploaded_at": S.iso(now), **meta}
    md = ingest.ingest_file(b["slug"], filename, data, extra_meta=extra, hold_until=learn_hold_until())
    ocr = _ocr_state(md)
    b["files"].append({"file": filename, "md": Path(md).name, "sha256": sha, "ocr": ocr})
    b["last_at"] = S.iso(now)
    return ocr


def _result(b: dict, ocr: str | None) -> dict:
    return {"status": "attached", "batch_id": b["id"], "slug": b["slug"], "count": len(b["files"]),
            "dupes": b["dupes"], "ocr": ocr or "done"}


def _duplicate(slug: str, dupes: int = 1) -> dict:
    return {"status": "duplicate", "batch_id": None, "slug": slug, "count": 0, "dupes": dupes, "ocr": None}


def _choice_open(st: dict, now: dt.datetime) -> bool:
    """A book question is waiting for CR's answer (10 min): photos must not use the old book."""
    pc = st["ui"].get("pending_choice")
    at = S.parse((pc or {}).get("at"))
    return bool(at) and now - at <= CHOICE_TTL


def pending_choice(now: dt.datetime | None = None) -> dict | None:
    now = _now(now)
    with S.LOCK:
        st = S.load()
    return dict(st["ui"]["pending_choice"]) if _choice_open(st, now) else None


def add_photo(file_bytes: bytes, filename: str, mime: str, *, caption: str = "",
              media_group_id: str | None = None, now: dt.datetime | None = None) -> dict:
    """Caption book > current book > holding.  Status ``attached`` / ``held`` / ``duplicate``.

    While a book question is open (``ui.pending_choice``) the current book is ignored.
    """
    now = _now(now)
    ext = _ext(filename, mime)
    with S.edit() as st:
        book, meta = _caption_meta(caption)
        album = st["albums"].get(media_group_id) if media_group_id else None
        if media_group_id and caption and album is None:
            st["albums"][media_group_id] = {"book": book, "meta": meta}
        elif album is not None and not caption:  # first caption applies to the whole album
            book, meta = album["book"], album["meta"]
        via_current = False
        if book is None:
            # holding is sticky: once photos wait for a book, every new photo waits with them
            fresh = _fresh(st["current_book"], now) and not _choice_open(st, now) and not st["holding"]
            cb = st["current_book"] if fresh else None
            if cb is None:
                return _hold(st, file_bytes, ext, caption, media_group_id, meta, now)
            book, via_current = {"slug": cb["slug"], "title": cb["title"]}, True
            cb["last_at"] = S.iso(now)
        b = _pick_batch(st, book["slug"], now, media_group_id)
        if b is None and hashlib.sha256(file_bytes).hexdigest() in _known_shas(book["slug"]):
            return _duplicate(book["slug"])  # never open a batch just for a duplicate
        if b is None:
            b = _new_batch(st, book["slug"], book["title"], now, via_current=via_current, mgid=media_group_id)
        ocr = _attach(st, b, file_bytes, ext, meta, now)
        _touch_recent(st, book["slug"], book["title"], now)
        return _result(b, ocr)


def _hold(st, data, ext, caption, mgid, meta, now) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    if any(h["sha256"] == sha for h in st["holding"]):
        return {"status": "held", "batch_id": None, "slug": None, "count": len(st["holding"]),
                "dupes": 1, "ocr": None}
    path = S.holding_dir() / f"{sha[:16]}{ext}"
    path.write_bytes(data)
    if not st["holding"]:  # a new holding generation (one purge warning per generation)
        st["holding_gen"] = st.get("holding_gen", 0) + 1
    st["holding"].append({"path": str(path), "ext": ext, "sha256": sha, "caption": caption or "",
                          "media_group_id": mgid, "meta": meta, "at": S.iso(now)})
    return {"status": "held", "batch_id": None, "slug": None, "count": len(st["holding"]),
            "dupes": 0, "ocr": None}


def purge_holding(max_age_hours: int = 24, now: dt.datetime | None = None) -> int:
    """Delete holding photos older than ``max_age_hours``; warn CR once an hour before.

    The warning goes out once per holding generation, when the oldest photo is
    ``max_age_hours - 1`` hours old.  Returns the number of photos deleted.
    """
    now = _now(now)
    limit = dt.timedelta(hours=max_age_hours)
    gone: list[dict] = []
    warn = 0
    with S.edit() as st:
        keep = []
        for h in st["holding"]:
            (gone if now - S.parse(h["at"]) >= limit else keep).append(h)
        st["holding"] = keep
        if gone and keep:  # survivors get their own warning later
            st["holding_gen"] = st.get("holding_gen", 0) + 1
        if not keep:
            st["ui"].pop("holding_msg", None)
        soon = [h for h in keep if now - S.parse(h["at"]) >= limit - dt.timedelta(hours=1)]
        if soon and st.get("holding_warned") != st.get("holding_gen"):
            st["holding_warned"] = st.get("holding_gen")
            warn = len(soon)
    for h in gone:  # state no longer lists them
        Path(h["path"]).unlink(missing_ok=True)
    if warn:
        try:
            from . import telegram_bot  # noqa: PLC0415 - the bot imports intake
            telegram_bot.warn_holding_purge(warn)
        except Exception as e:  # noqa: BLE001 - purging must not fail because Telegram did
            log.warning("보류함 정리 알림 실패: %s", e)
    return len(gone)


def batch_ocr(batch_id: str) -> dict | None:
    """Read state of a batch from its md files: ``{"done", "pending", "underlines": [...]}``."""
    b = get_batch(batch_id)
    if b is None:
        return None
    d = get_settings().data_dir / "books" / b["slug"] / "raw"
    done = pending = 0
    marks: list[str] = []
    for f in b["files"]:
        try:
            meta, body = store.read_md(d / f["md"])
        except (OSError, ValueError):
            continue
        if meta.get("ocr") == "pending":
            pending += 1
        else:
            done += 1
            marks += M.mark_lines(body)
    return {"done": done, "pending": pending, "underlines": marks}


def holding_count() -> int:
    with S.LOCK:
        return len(S.load()["holding"])


def resolve_holding(slug: str, title: str, now: dt.datetime | None = None) -> dict:
    """Attach everything in holding to one book (as one new batch) and make it the current book.

    Each photo is handled on its own: a failure leaves that photo in holding.  Progress is
    saved even if something unexpected escapes, and holding files are deleted only after
    the state that no longer lists them has been saved.
    """
    now = _now(now)
    done_paths: list[Path] = []
    failed = 0
    with S.edit(save_on_error=True) as st:
        if not st["holding"]:
            return {"status": "empty", "batch_id": None, "slug": slug, "count": 0, "dupes": 0, "ocr": None}
        ensure_book(slug, title)
        b = _new_batch(st, slug, title, now, via_current=True, mgid=None)
        ocr = None
        for h in list(st["holding"]):
            p = Path(h["path"])
            try:
                if p.is_file():
                    o = _attach(st, b, p.read_bytes(), h.get("ext") or p.suffix, h.get("meta") or {}, now)
                    ocr = "pending" if "pending" in (ocr, o) else (o or ocr)
            except Exception as e:  # noqa: BLE001 - keep the photo in holding, go on with the rest
                log.warning("보류함 사진 붙이기 실패(보류함에 남김): %s", e)
                failed += 1
                continue
            st["holding"].remove(h)
            done_paths.append(p)
        st["current_book"] = {"slug": slug, "title": title, "set_at": S.iso(now), "last_at": S.iso(now)}
        st["ui"].pop("pending_choice", None)
        _touch_recent(st, slug, title, now)
        if not b["files"]:  # all duplicates (or all failed): no empty batch
            st["batches"].remove(b)
            res = _duplicate(slug, b["dupes"]) if not failed else {
                "status": "failed", "batch_id": None, "slug": slug, "count": 0, "dupes": b["dupes"], "ocr": None}
        else:
            res = _result(b, ocr)
        res["failed"] = failed
    for p in done_paths:  # state no longer points at them: now it is safe to delete
        p.unlink(missing_ok=True)
    return res


def discard_holding() -> int:
    with S.edit() as st:
        items, st["holding"] = st["holding"], []
    for h in items:
        Path(h["path"]).unlink(missing_ok=True)
    return len(items)


# ---------------------------------------------------------------------------
# batches: lookup, move, delete
# ---------------------------------------------------------------------------

def get_batch(batch_id: str) -> dict | None:
    with S.LOCK:
        return next((dict(b) for b in S.load()["batches"] if b["id"] == batch_id), None)


def recent_batches(n: int = 3) -> list[dict]:
    with S.LOCK:
        return [dict(b) for b in reversed(S.load()["batches"])][:n]


def update_batch(batch_id: str, **fields) -> None:
    """Store UI bits on a batch (its confirmation message, cached keyboard)."""
    with S.edit() as st:
        for b in st["batches"]:
            if b["id"] == batch_id:
                b.update(fields)


def set_batch_message(batch_id: str, chat_id, message_id) -> None:
    update_batch(batch_id, message={"chat_id": chat_id, "message_id": message_id})


def confirm_batch(batch_id: str) -> bool:
    with S.edit() as st:
        for b in st["batches"]:
            if b["id"] == batch_id:
                b["confirmed"] = True
                return True
    return False


# file / hook helpers live in intake_state (keeps this module small)
_forget = S.forget_file
_ocr_module = S.ocr_module
_ocr_pending_entry = S.take_ocr_pending
_move_files = S.move_files
_rehome = S.rehome


def move_batch(batch_id: str, new_slug: str, new_title: str | None = None) -> dict:
    """Move every file of a batch to another book (re-registered there, new catalog ids).

    Files are moved one by one.  If some fail, they stay in the old book as a separate batch,
    and the state is saved even when something unexpected escapes.
    """
    with S.edit(save_on_error=True) as st:
        b = next((x for x in st["batches"] if x["id"] == batch_id), None)
        if b is None:
            return {"ok": False, "reason": "unknown_batch"}
        old = b["slug"]
        new_title = new_title or book_title(new_slug)
        if old == new_slug:
            return {"ok": True, "moved": 0, "dupes": 0, "failed": 0, "from": old, "to": new_slug}
        ensure_book(new_slug, new_title)
        src_dir, dst_dir = store.raw_dir(old), store.raw_dir(new_slug)
        target_shas = _known_shas(new_slug)
        moved, failed, dupes = [], [], 0
        for f in b["files"]:
            if f["sha256"] in target_shas:  # already in the target book: drop this copy
                _ocr_pending_entry(old, f["file"])
                _forget(old, f["file"])
                (src_dir / f["file"]).unlink(missing_ok=True)
                (src_dir / f["md"]).unlink(missing_ok=True)
                dupes += 1
                continue
            try:
                _move_files(f, src_dir, dst_dir, new_slug)
            except Exception as e:  # noqa: BLE001 - this photo stays in the old book
                log.warning("사진 옮기기 실패(원래 책에 남김): %s", e)
                failed.append(f)
                continue
            _rehome(old, new_slug, f, dst_dir)
            moved.append(f)
        if not moved and not dupes:
            return {"ok": False, "reason": "failed", "moved": 0, "dupes": 0, "failed": len(failed),
                    "from": old, "to": new_slug}
        if failed:  # what could not move stays where it is, as its own batch
            rest = _new_batch(st, old, b["title"], S.now_seoul(), via_current=b.get("via_current", False),
                              mgid=None)
            rest["files"] = failed
        b.update(slug=new_slug, title=new_title, files=moved, dupes=b["dupes"] + dupes)
        switched = False
        cb = st["current_book"]
        if moved and b.get("via_current") and cb and cb["slug"] == old:
            cb.update(slug=new_slug, title=new_title)
            switched = True
        _touch_recent(st, new_slug, new_title, S.now_seoul())
    index.rebuild()
    return {"ok": True, "moved": len(moved), "dupes": dupes, "failed": len(failed), "from": old,
            "to": new_slug, "current_switched": switched}


def delete_batch(batch_id: str) -> dict:
    """Delete the files of a batch (original + md) and drop it from catalog / graph / OCR queue."""
    with S.edit() as st:
        b = next((x for x in st["batches"] if x["id"] == batch_id), None)
        if b is None:
            return {"ok": False, "reason": "unknown_batch"}
        d = store.raw_dir(b["slug"])
        for f in b["files"]:
            _ocr_pending_entry(b["slug"], f["file"])
            _forget(b["slug"], f["file"])
            (d / f["file"]).unlink(missing_ok=True)
            (d / f["md"]).unlink(missing_ok=True)
        st["batches"] = [x for x in st["batches"] if x["id"] != batch_id]
    index.rebuild()
    return {"ok": True, "deleted": len(b["files"]), "slug": b["slug"], "seq": b["seq"]}


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def ocr_pending_count() -> int:
    ocr = _ocr_module()
    lister = getattr(ocr, "list_pending", None) if ocr else None
    if lister:
        try:
            return len(lister())
        except Exception:  # noqa: BLE001 - a status line must never fail
            return 0
    return 0


def summary() -> dict:
    books = [{"slug": b["slug"], "title": b.get("title") or b["slug"], "count": book_count(b["slug"])}
             for b in store.list_books()]
    books.sort(key=lambda b: -b["count"])
    try:
        unclassified = len(catalog.pending(include_held=True))  # grace-period items wait too
    except Exception:  # noqa: BLE001
        unclassified = 0
    return {"books": books, "ocr_pending": ocr_pending_count(), "unclassified": unclassified,
            "holding": holding_count()}
