"""OCR provider chain (free providers only) + pending queue for Clair's manual transcription."""
import base64
import datetime as dt
import json
import time
from pathlib import Path

import httpx

from . import catalog, llm, store, think
from .config import get_settings

_OCR_PROVIDERS = ("anthropic", "gemini")


class OcrUnavailable(Exception):
    """Every configured OCR provider failed (or none is available)."""

    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("OCR을 쓸 수 없어요: " + "; ".join(self.reasons or ["제공자 없음"]))


# ---------------------------------------------------------------------------
# usage cap
# ---------------------------------------------------------------------------

def ocr_daily_count() -> int:
    p = think._usage_path()
    if not p.is_file():
        return 0
    n = 0
    for line in p.read_text("utf-8").splitlines():
        try:
            if json.loads(line).get("kind") == "ocr":
                n += 1
        except (ValueError, AttributeError):
            continue
    return n


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------

def _gemini_ocr(data: bytes, mime: str) -> tuple[str, str, int, int]:
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("no gemini key")
    model = s.gemini_model_fast
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"system_instruction": {"parts": [{"text": llm.OCR_SYSTEM}]},
            "contents": [{"parts": [
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
                {"text": "Transcribe this page."}]}]}
    r = httpx.post(url, json=body, timeout=think.HTTP_TIMEOUT,
                   headers={"x-goog-api-key": s.gemini_api_key})
    r.raise_for_status()
    j = r.json()
    parts = j["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts)
    u = j.get("usageMetadata") or {}
    return text, model, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


def _anthropic_ocr(data: bytes, mime: str) -> tuple[str, str, int, int]:
    return llm.ocr_image(data, mime), get_settings().model_fast, 0, 0


def ocr_image(data: bytes, mime: str) -> str:
    """Transcribe one image with the first working provider in ``think_providers``."""
    s = get_settings()
    if ocr_daily_count() >= s.ocr_daily_cap:
        raise OcrUnavailable([f"하루 OCR 상한({s.ocr_daily_cap}장)에 닿았어요"])
    names = [p.strip() for p in s.think_providers.split(",")]
    chain = [p for p in names if p in _OCR_PROVIDERS]
    if not chain:
        raise OcrUnavailable(["OCR을 쓸 수 있는 제공자가 없어요"])
    reasons = []
    for p in chain:
        if not getattr(s, f"{p}_api_key", ""):
            reasons.append(f"{p}: 키 없음")
            continue
        t0 = time.monotonic()
        try:
            text, model, tin, tout = (_gemini_ocr if p == "gemini" else _anthropic_ocr)(data, mime)
            if not text.strip():
                raise ValueError("empty text")
        except Exception as e:  # any provider failure falls through to the next one
            reasons.append(think._reason(p, e))
            continue
        think.record_usage("ocr", p, model, tin, tout, time.monotonic() - t0)
        return text
    raise OcrUnavailable(reasons)


# ---------------------------------------------------------------------------
# pending queue
# ---------------------------------------------------------------------------

def pending_path() -> Path:
    d = get_settings().data_dir / "ocr"
    d.mkdir(parents=True, exist_ok=True)
    return d / "pending.jsonl"


def list_pending() -> list[dict]:
    p = pending_path()
    if not p.is_file():
        return []
    out = []
    for line in p.read_text("utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _write_all(rows: list[dict]) -> None:
    p = pending_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(p)


def add_pending(entry: dict) -> dict:
    """Queue one file for manual transcription. Idempotent by id."""
    entry = dict(entry)
    entry.setdefault("id", catalog.make_id(entry["book"], entry["file"]))
    entry.setdefault("added_at", dt.datetime.now().isoformat(timespec="seconds"))
    rows = [r for r in list_pending() if r["id"] != entry["id"]]
    rows.append(entry)
    _write_all(rows)
    return entry


def remove_pending(entry_id: str) -> None:
    _write_all([r for r in list_pending() if r["id"] != entry_id])


def complete(entry_id: str, text: str) -> dict:
    """Fill the markdown body with Clair's transcription and put the file on the learn queue."""
    entry = next((r for r in list_pending() if r["id"] == entry_id), None)
    if entry is None:
        raise KeyError(entry_id)
    md = Path(entry["path"])
    meta, _ = store.read_md(md)
    meta["ocr"] = "done"
    store.write_md(md, meta, text)
    catalog.register(entry["book"], entry["file"], md, meta.get("sha256", ""))
    remove_pending(entry_id)
    try:  # tell CR on Telegram; never let a notification break the submission
        from . import telegram_bot  # noqa: PLC0415 - lazy: the bot imports intake/ingest
        telegram_bot.notify_ocr_done(entry)
    except Exception:  # noqa: BLE001
        pass
    return entry
