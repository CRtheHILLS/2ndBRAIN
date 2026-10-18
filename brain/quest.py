"""Quest state files: paths, creation, load/save, log and source ledger.

Layout under ``DATA_DIR/quests/<slug>``: ``quest.json``, ``log.jsonl``,
``sources.json``.  The runner (stages, tasks) lives elsewhere.
"""
import datetime as dt
import json
import re
from pathlib import Path

from . import models
from .config import get_settings
from .slug import slugify

_ENDINGS = re.compile(
    r"\s*(을|를)?\s*(배우고\s*싶(어|어요|다)|이해하고\s*싶(어|어요|다)|알고\s*싶(어|어요|다)|"
    r"공부하자|공부하고\s*싶(어|어요|다)|가르쳐\s*줘(요)?|가르쳐\s*주세요|알려\s*줘(요)?)\s*$")
_LEAD = re.compile(r"^\s*(나|저)\s+")


def quests_root() -> Path:
    p = get_settings().data_dir / "quests"
    p.mkdir(parents=True, exist_ok=True)
    return p


def quest_dir(slug: str) -> Path:
    return quests_root() / slug


def normalize_sentence(s: str) -> str:
    t = s.lower()
    t = re.sub(r"[^\w\s]|_", " ", t)  # punctuation and emoji
    t = re.sub(r"\s+", " ", t).strip()
    t = _LEAD.sub("", t)
    t = _ENDINGS.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def slug_for(sentence: str) -> str:
    body = slugify(normalize_sentence(sentence) or sentence)[:40].strip("-")
    return f"quest-{dt.date.today():%Y%m%d}-{body}".rstrip("-")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def load(slug: str) -> dict:
    return json.loads((quest_dir(slug) / "quest.json").read_text("utf-8"))


def save(slug: str, q: dict) -> None:
    q["updated_at"] = _now()
    d = quest_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "quest.json").write_text(json.dumps(q, ensure_ascii=False, indent=2), "utf-8")


def list_quests() -> list[dict]:
    out = []
    for p in quests_root().glob("*/quest.json"):
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(out, key=lambda q: (q.get("created_at", ""), q.get("slug", "")), reverse=True)


def find_existing(sentence: str) -> str | None:
    key = normalize_sentence(sentence)
    if not key:
        return None
    for q in list_quests():  # newest first
        if normalize_sentence(q.get("sentence", "")) == key:
            return q["slug"]
    return None


def _extract_days(sentence: str) -> int:
    if re.search(r"하루|오늘 안에|하룻밤", sentence):
        return 1
    m = re.search(r"(\d{1,2})\s*일", sentence)
    if m and 1 <= int(m.group(1)) <= 30:
        return int(m.group(1))
    return 7


def _extract_level(sentence: str) -> str:
    if "전문" in sentence:
        return "전문"
    if "일반" in sentence or "교양" in sentence:
        return "일반"
    return "초등"


def create(sentence: str, days: int | None = None, level: str | None = None,
           started_by: str = "cli") -> dict:
    existing = find_existing(sentence)
    if existing:
        q = load(existing)
        q["existing"] = True
        return q
    slug = slug_for(sentence)
    base, n = slug, 2
    while quest_dir(slug).exists():
        slug = f"{base}-{n}"
        n += 1
    now = _now()
    q = {
        "slug": slug, "sentence": sentence,
        "days_requested": days if days is not None else _extract_days(sentence),
        "level": level or _extract_level(sentence),
        "status": "queued", "stage_done": [], "plan": None,
        "created_at": now, "updated_at": now, "started_by": started_by,
        "error": None, "summary": {},
        "budget": {"think_calls": 0, "sources": 0, "seconds": 0.0},
    }
    save(slug, q)
    q["existing"] = False
    return q


def log(slug: str, **fields) -> None:
    d = quest_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": _now(), **fields}, ensure_ascii=False) + "\n")


def save_ledger(slug: str, ledger: models.SourceLedger) -> None:
    d = quest_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "sources.json").write_text(ledger.model_dump_json(indent=2), "utf-8")


def load_ledger(slug: str) -> models.SourceLedger:
    p = quest_dir(slug) / "sources.json"
    if not p.is_file():
        return models.SourceLedger()
    return models.SourceLedger.model_validate_json(p.read_text("utf-8"))
