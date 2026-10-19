"""Retry scheduler: resumes quests parked on a thinker and recovers after a server restart."""
import datetime as dt
import logging
import threading

from . import quest
from .config import get_settings

log = logging.getLogger(__name__)
_stop = threading.Event()
_thread: threading.Thread | None = None


def _parse(ts: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def tick(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now()
    s = get_settings()
    out: dict = {"resumed": [], "skipped": []}
    for q in quest.list_quests():
        slug = q.get("slug", "?")
        try:
            status = q.get("status")
            if status in ("running", "queued"):
                if quest.is_running(slug):
                    out["skipped"].append(f"{slug}: 실행 중")
                    continue
                quest.resume(slug)  # server restart recovery / never started
                out["resumed"].append(slug)
            elif status == "waiting_thinker":
                updated, created = _parse(q.get("updated_at")), _parse(q.get("created_at"))
                waiting = (q.get("summary") or {}).get("waiting_task")
                if waiting and quest.task_result(slug, waiting) is not None and not quest.is_running(slug):
                    quest.resume(slug)  # the answer is already in: no reason to wait for the retry window
                    out["resumed"].append(slug)
                elif updated is None or created is None:
                    out["skipped"].append(f"{slug}: 시각 정보 없음")
                elif now - created > dt.timedelta(hours=s.think_retry_hours):
                    out["skipped"].append(f"{slug}: 재시도 기간 지남")
                elif now - updated < dt.timedelta(minutes=s.think_retry_minutes):
                    out["skipped"].append(f"{slug}: 아직 이름")
                else:
                    quest.resume(slug)
                    out["resumed"].append(slug)
            else:
                out["skipped"].append(f"{slug}: {status}")
        except Exception:  # noqa: BLE001 - one bad quest must not stop the loop
            log.exception("scheduler: quest %s failed", slug)
            out["skipped"].append(f"{slug}: 오류")
    return out


def _loop() -> None:
    delay = 5.0
    while not _stop.wait(delay):
        try:
            tick()
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick failed")
        delay = 60.0


def start() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="quest-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
