from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from brain.config import get_settings

from .base import UA, Candidate, Doc
from .ddgs_web import guess_kind

log = logging.getLogger(__name__)

# Set by collect.collect_quest while a quest collects, so search costs also land in its log.jsonl.
CURRENT_LOG: Path | None = None


def _parse(text: str) -> list[dict]:
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b <= a:
        return []
    try:
        data = json.loads(text[a:b + 1])
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("url")]


def _record(body: dict, model: str, seconds: float) -> None:
    """Meter the Responses API call (daily usage file + the running quest's log)."""
    usage = body.get("usage") or {}
    try:
        from brain import think
        think.record_usage("search", "xai", body.get("model") or model, int(usage.get("input_tokens") or 0),
                           int(usage.get("output_tokens") or 0), seconds, log_path=CURRENT_LOG)
    except Exception as e:  # noqa: BLE001 - metering must not break search
        log.warning("xai usage record failed: %s", e)


def search(query: str, lang: str, limit: int) -> list[Candidate]:
    s = get_settings()
    if not s.xai_api_key:
        return []
    prompt = f"{query}\n\n다음 주제의 좋은 출처 URL {limit}개를 JSON 배열 [{{url,title,kind}}]로만 답하세요."
    t0 = time.monotonic()
    r = httpx.post(
        "https://api.x.ai/v1/responses",
        headers={"Authorization": f"Bearer {s.xai_api_key}", "User-Agent": UA},
        json={"model": s.xai_model_fast, "input": prompt, "tools": [{"type": "web_search"}]},
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    _record(body, s.xai_model_fast, time.monotonic() - t0)
    text = "".join(
        part.get("text", "")
        for item in body.get("output", []) if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") == "output_text"
    )
    return [
        Candidate(url=d["url"], title=d.get("title") or d["url"], kind=guess_kind(d["url"]),
                  connector="xai", lang=lang)
        for d in _parse(text)[:limit]
    ]


class XaiConnector:
    name = "xai"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        return search(query, lang, limit)

    def fetch(self, c: Candidate) -> Doc | None:
        return None
