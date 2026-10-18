"""20-year knowledge taxonomy (17 areas, ~150 fields). Add-only codes.

Codes are never reused or deleted: a retired field gets ``deprecated_to``
pointing at its replacement and ``resolve_code`` follows the chain.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).with_name("frame") / "taxonomy.json"

_DOMAIN_AREA = {
    "과학": "B", "역사": "J", "종교": "K", "철학": "K", "심리": "H", "경제": "I",
    "기술": "F", "예술": "M", "동물": "O", "건강": "N", "기타": "Z",
}


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(_PATH.read_text(encoding="utf-8"))


def fields() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for a in load()["areas"]:
        for f in a["fields"]:
            out[f["code"]] = {**f, "area": a["code"]}
    return out


def is_valid_code(code: str) -> bool:
    return code in fields()


def resolve_code(code: str) -> str:
    """Follow deprecated_to; on a cycle (or unknown code) return the original."""
    f = fields()
    cur, seen = code, {code}
    while cur in f and f[cur].get("deprecated_to"):
        cur = f[cur]["deprecated_to"]
        if cur in seen:
            return code
        seen.add(cur)
    return cur


def area_of(code: str) -> str:
    f = fields().get(code)
    return f["area"] if f else code[:1]


def domain_to_area(domain: str) -> str:
    return _DOMAIN_AREA.get(domain, "Z")


def validate() -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    all_codes: set[str] = set()
    for a in load()["areas"]:
        for f in a["fields"]:
            all_codes.add(f["code"])
    for a in load()["areas"]:
        for f in a["fields"]:
            c = f["code"]
            if c in seen:
                problems.append(f"duplicate code {c}")
            seen.add(c)
            if not c.startswith(a["code"]):
                problems.append(f"{c} does not belong to area {a['code']}")
            dep = f.get("deprecated_to")
            if dep and dep not in all_codes:
                problems.append(f"{c}.deprecated_to {dep} is unknown")
    return problems


def field_prompt_list() -> str:
    lines = []
    for a in load()["areas"]:
        for f in a["fields"]:
            if not f.get("deprecated_to"):
                lines.append(f"{f['code']} {f['name_ko']} ({f['name_en']})")
    return "\n".join(lines)
