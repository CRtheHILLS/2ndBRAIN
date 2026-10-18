"""20-year knowledge taxonomy (17 areas, ~150 fields). Add-only codes.

Codes are never reused or deleted: a retired field gets ``deprecated_to``
pointing at its replacement and ``resolve_code`` follows the chain.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_CODE_RE = re.compile(r"^[A-Z]\d+$")
FALLBACK_CODE = "Z6"  # filing spot for anything that cannot be placed
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
    areas = load()["areas"]
    area_codes: set[str] = set()
    owner: dict[str, str] = {}
    for a in areas:
        if a["code"] in area_codes:
            problems.append(f"duplicate area {a['code']}")
        area_codes.add(a["code"])
        for f in a["fields"]:
            c = f["code"]
            if not _CODE_RE.match(c):
                problems.append(f"bad code format {c}")
            if c in owner:
                problems.append(f"duplicate code {c}")
            owner[c] = a["code"]
            if not c.startswith(a["code"]):
                problems.append(f"{c} does not belong to area {a['code']}")
    for c in owner:
        dep = next(f for a in areas for f in a["fields"] if f["code"] == c).get("deprecated_to")
        if not dep:
            continue
        if dep == c:
            problems.append(f"{c}.deprecated_to points to itself")
        elif dep not in owner:
            problems.append(f"{c}.deprecated_to {dep} is unknown")
    f = fields()
    for c in owner:
        cur, seen = c, {c}
        while f[cur].get("deprecated_to") in f:
            cur = f[cur]["deprecated_to"]
            if cur in seen:
                if f[c].get("deprecated_to") != c:
                    problems.append(f"deprecated_to cycle at {c}")
                break
            seen.add(cur)
    return problems


def field_prompt_list() -> str:
    lines = []
    for a in load()["areas"]:
        for f in a["fields"]:
            if f.get("deprecated_to") or f.get("fallback"):
                continue
            line = f"{f['code']} {f['name_ko']} ({f['name_en']})"
            if f.get("note"):
                line += f" — {f['note']}"
            lines.append(line)
    return "\n".join(lines)
