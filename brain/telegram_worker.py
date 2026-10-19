"""Single ordered worker for Telegram updates, with media-group (album) buffering.

Updates are processed strictly in ``update_id`` order. An album (updates sharing a
``media_group_id``) is held until its window closes, then released as a block at its first
member's position; later updates wait behind it. A caption on any member is copied onto the rest.
"""
import logging
import threading
import time
from collections import deque

from .config import get_settings

log = logging.getLogger(__name__)

ALBUM_WINDOW = 2.0
ALBUM_MAX = 10

_lock = threading.Condition()
_proc = threading.Lock()  # one handler call at a time, whichever thread drives
_pending: list[dict] = []  # {"id", "update", "mgid"}
_seen_ids: deque = deque(maxlen=2000)
_seen_set: set = set()
_last_seen: dict[str, float] = {}  # media_group_id -> arrival time of the newest member
_thread: threading.Thread | None = None
_stop = threading.Event()
_busy = False
_clock = time.monotonic
_handler = None


def set_handler(fn) -> None:
    global _handler
    _handler = fn


def _handle(update: dict) -> None:
    if _handler is not None:
        _handler(update)
        return
    from . import telegram_bot
    telegram_bot.handle_update(update, telegram_bot.TelegramAPI(get_settings().telegram_bot_token))


def _mask(text) -> str:
    token = get_settings().telegram_bot_token
    out = str(text)
    return out.replace(token, "***") if token else out


def _msg(update: dict) -> dict:
    return update.get("message") or update.get("edited_message") or {}


def _mgid(update: dict) -> str | None:
    mg = _msg(update).get("media_group_id")
    return str(mg) if mg else None


def enqueue(update: dict, now: float | None = None) -> None:
    uid = update.get("update_id")
    now = _clock() if now is None else now
    with _lock:
        if uid is not None:
            if uid in _seen_set:
                return
            if len(_seen_ids) == _seen_ids.maxlen:
                _seen_set.discard(_seen_ids[0])
            _seen_ids.append(uid)
            _seen_set.add(uid)
        mg = _mgid(update)
        _pending.append({"id": uid if uid is not None else 0, "update": update, "mgid": mg})
        _pending.sort(key=lambda p: p["id"])
        if mg:
            _last_seen[mg] = now
        _lock.notify_all()


def pending_count() -> int:
    with _lock:
        return len(_pending) + (1 if _busy else 0)


def _share_caption(updates: list[dict]) -> None:
    caption = next((_msg(u)["caption"] for u in updates if _msg(u).get("caption")), "")
    if not caption:
        return
    for u in updates:
        m = _msg(u)
        if not m.get("caption"):
            m["caption"] = caption


def _next_batch(now: float) -> list[dict] | None:
    """Pop the next releasable run (one update, or one whole album), else None. Call with _lock held."""
    if not _pending:
        return None
    head = _pending[0]
    mg = head["mgid"]
    if not mg:
        _pending.pop(0)
        return [head["update"]]
    members = [p for p in _pending if p["mgid"] == mg]
    if len(members) < ALBUM_MAX and now - _last_seen.get(mg, now) < ALBUM_WINDOW:
        return None
    _pending[:] = [p for p in _pending if p["mgid"] != mg]
    _last_seen.pop(mg, None)
    return [p["update"] for p in members]


def _tick(now: float) -> int:
    """Process everything releasable at time ``now``; returns the number of updates handled."""
    global _busy
    handled = 0
    with _proc:
        while True:
            with _lock:
                batch = _next_batch(now)
                _busy = batch is not None
            if batch is None:
                return handled
            _share_caption(batch)
            for u in batch:
                try:
                    _handle(u)
                except Exception as e:  # noqa: BLE001 - the worker must survive any handler error
                    log.error("텔레그램 업데이트 처리 실패: %s", _mask(e))
                handled += 1
            with _lock:
                _busy = False


def _loop() -> None:
    while not _stop.is_set():
        try:
            _tick(_clock())
        except Exception as e:  # noqa: BLE001
            log.error("텔레그램 워커 오류: %s", _mask(e))
        with _lock:
            _lock.wait(0.25)


def drain(timeout: float = 10.0) -> bool:
    """Wait until nothing is pending (driving the queue itself if the thread isn't running)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _thread is None or not _thread.is_alive():
            _tick(_clock())
        if pending_count() == 0:
            return True
        time.sleep(0.02)
    return pending_count() == 0


def start() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="telegram-worker", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    with _lock:
        _lock.notify_all()
    t, _thread = _thread, None
    if t is not None and t.is_alive():
        t.join(timeout=2)


def reset() -> None:
    """Forget all queued state and the injected handler (tests)."""
    global _handler
    with _lock:
        _pending.clear()
        _seen_ids.clear()
        _seen_set.clear()
        _last_seen.clear()
    _handler = None
