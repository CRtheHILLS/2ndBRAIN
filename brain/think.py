"""Provider chain for every LLM call that expects text or JSON back.

Order comes from ``THINK_PROVIDERS`` (default anthropic -> gemini -> xai).  A provider
without an API key is skipped; any exception or non-2xx answer moves the chain on.
``think()`` adds JSON parsing, optional pydantic validation, one retry per provider and
a daily call cap.  OCR stays on ``llm.ocr_image``.
"""

import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from .config import get_settings

SMART_KINDS = {"plan", "teach", "bridge", "ask"}
HTTP_TIMEOUT = 120.0
RETRY_SUFFIX = "\n\nJSON 객체만 출력하라. 설명, 마크다운 펜스, 인사말 없이 JSON 객체 하나만."


class ThinkUnavailable(Exception):
    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons) or "no provider available")


@dataclass
class ThinkResult:
    data: dict
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    seconds: float


def parse_json(raw: str) -> dict | None:
    """Salvage the outermost {...} (also strips ```json fences and chatter)."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        d = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


# ---------------------------------------------------------------------------
# adapters: (system, user, model) -> (text, input_tokens, output_tokens)
# ---------------------------------------------------------------------------

def _anthropic(system: str, user: str, model: str) -> tuple[str, int, int]:
    from . import llm
    r = llm._client().messages.create(model=model, max_tokens=8000, system=system,
                                      messages=[{"role": "user", "content": user}])
    usage = getattr(r, "usage", None)
    return (llm._first_text(r), getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0)


def _gemini(system: str, user: str, model: str) -> tuple[str, int, int]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    r = httpx.post(url, json=body, timeout=HTTP_TIMEOUT,
                   headers={"x-goog-api-key": get_settings().gemini_api_key})
    r.raise_for_status()
    j = r.json()
    parts = j["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts)
    u = j.get("usageMetadata") or {}
    return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


def _xai(system: str, user: str, model: str) -> tuple[str, int, int]:
    body = {"model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
    r = httpx.post("https://api.x.ai/v1/chat/completions", json=body, timeout=HTTP_TIMEOUT,
                   headers={"Authorization": f"Bearer {get_settings().xai_api_key}"})
    r.raise_for_status()
    j = r.json()
    u = j.get("usage") or {}
    return j["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


_ADAPTERS = {"anthropic": "_anthropic", "gemini": "_gemini", "xai": "_xai"}


def _has_key(provider: str) -> bool:
    return bool(getattr(get_settings(), f"{provider}_api_key", ""))


def _model_for(provider: str, smart: bool) -> str:
    s = get_settings()
    if provider == "anthropic":
        return s.model_smart if smart else s.model_fast
    return getattr(s, f"{provider}_model_{'smart' if smart else 'fast'}")


def _order() -> list[str]:
    names = [p.strip() for p in get_settings().think_providers.split(",")]
    return [p for p in names if p in _ADAPTERS]


def providers_available() -> list[str]:
    return [p for p in _order() if _has_key(p)]


def _call(provider: str, system: str, user: str, model: str) -> tuple[str, int, int]:
    # looked up by name so monkeypatching the module attribute works
    return globals()[_ADAPTERS[provider]](system, user, model)


# ---------------------------------------------------------------------------
# usage log / daily cap
# ---------------------------------------------------------------------------

def _usage_path() -> Path:
    d = get_settings().data_dir / "think"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"usage-{dt.date.today().isoformat()}.jsonl"


def daily_count() -> int:
    """Think calls today (``search`` rows from the xAI connector are metered but not counted)."""
    p = _usage_path()
    if not p.is_file():
        return 0
    n = 0
    for line in p.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            if json.loads(line).get("kind") in ("search", "ocr"):
                continue
        except (ValueError, AttributeError):
            pass
        n += 1
    return n


def record_usage(kind: str, provider: str, model: str, input_tokens: int, output_tokens: int,
                 seconds: float, log_path: Path | None = None) -> None:
    row = {"at": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind, "provider": provider,
           "model": model, "in": input_tokens, "out": output_tokens, "sec": round(seconds, 2)}
    line = json.dumps(row, ensure_ascii=False) + "\n"
    for path in (_usage_path(), log_path):
        if path is not None:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def _reason(provider: str, e: Exception) -> str:
    """Failure reason without URLs or keys (httpx messages embed the request URL)."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"{provider}: HTTP {e.response.status_code}"
    return f"{provider}: {type(e).__name__}"


def _is_transient(e: Exception) -> bool:
    """5xx / 429 / timeout: worth one retry on the same provider's fast model."""
    if isinstance(e, httpx.HTTPStatusError):
        c = e.response.status_code
        return c >= 500 or c == 429
    if isinstance(e, httpx.TimeoutException):
        return True
    try:
        import anthropic
    except ImportError:
        return False
    if isinstance(e, (anthropic.RateLimitError, anthropic.InternalServerError,
                      anthropic.APITimeoutError)):
        return True
    if isinstance(e, anthropic.APIStatusError):
        c = getattr(e, "status_code", 0) or 0
        return c >= 500 or c == 429
    return False


def _call_with_fast_fallback(p: str, system: str, user: str, smart: bool):
    """-> (text, in, out, model).  A transient smart-model failure retries once on fast."""
    model = _model_for(p, smart)
    try:
        return (*_call(p, system, user, model), model)
    except Exception as e:  # noqa: BLE001
        fast = _model_for(p, False)
        if not (smart and _is_transient(e) and fast and fast != model):
            raise
        return (*_call(p, system, user, fast), fast)


def _schema_reason(provider: str, e: ValidationError) -> str:
    errs = e.errors()
    path = ".".join(str(x) for x in errs[0]["loc"]) if errs else ""
    return f"{provider}: schema: {path or '?'}"


def complete_text(system: str, user: str, smart: bool) -> tuple[str, str, str, int, int]:
    """First provider that answers wins -> (text, provider, model, in_tok, out_tok)."""
    if daily_count() >= get_settings().think_daily_cap:
        raise ThinkUnavailable(["daily cap"])
    reasons: list[str] = []
    for p in _order():
        if not _has_key(p):
            reasons.append(f"{p}: no key")
            continue
        t0 = time.monotonic()
        try:
            text, i, o, model = _call_with_fast_fallback(p, system, user, smart)
        except Exception as e:  # noqa: BLE001 - any failure moves the chain on
            reasons.append(_reason(p, e))
            continue
        record_usage("text", p, model, i, o, time.monotonic() - t0)
        return text, p, model, i, o
    raise ThinkUnavailable(reasons)


def think(kind: str, system: str, user: str, schema: type[BaseModel] | None = None, *,
          smart: bool | None = None, log_path: Path | None = None) -> ThinkResult:
    s = get_settings()
    if daily_count() >= s.think_daily_cap:
        raise ThinkUnavailable(["daily cap"])
    if smart is None:
        smart = kind in SMART_KINDS
    reasons: list[str] = []
    for p in _order():
        if not _has_key(p):
            reasons.append(f"{p}: no key")
            continue
        fail = f"{p}: bad json"
        for attempt in (0, 1):
            t0 = time.monotonic()
            try:
                text, i, o, model = _call_with_fast_fallback(
                    p, system, user + (RETRY_SUFFIX if attempt else ""), smart)
            except Exception as e:  # noqa: BLE001
                reasons.append(_reason(p, e))
                break
            secs = time.monotonic() - t0
            record_usage(kind, p, model, i, o, secs, log_path)
            data = parse_json(text or "")
            fail = f"{p}: bad json"
            if data is not None and schema is not None:
                try:
                    data = schema.model_validate(data).model_dump()
                except ValidationError as ve:
                    data = None
                    fail = _schema_reason(p, ve)
            if data is not None:
                return ThinkResult(data, p, model, i, o, secs)
            if attempt:
                reasons.append(fail)
    raise ThinkUnavailable(reasons)
