"""Wikidata lookups used to anchor concepts to a permanent QID."""
from . import base

API = "https://www.wikidata.org/w/api.php"


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def search_entity(label: str, lang: str) -> dict | None:
    """First wbsearchentities hit whose label/alias equals ``label`` (normalized), else None."""
    want = _norm(label)
    if not want:
        return None
    try:
        data = base.http_get(API, params={
            "action": "wbsearchentities", "search": label, "language": lang, "uselang": lang,
            "type": "item", "limit": 5, "format": "json"}, timeout=10).json()
        for it in data.get("search", []):
            desc = (it.get("description") or "").lower()
            if "disambiguation" in desc or "동음이의" in desc:
                continue
            aliases = list(it.get("aliases") or [])
            if _norm(it.get("label") or "") == want or want in {_norm(a) for a in aliases}:
                return {"id": it["id"], "label": it.get("label", ""),
                        "description": it.get("description", ""), "aliases": aliases}
    except Exception:
        return None
    return None


def parents(qid: str) -> list[str]:
    """QIDs this item is a subclass of (P279) or an instance of (P31)."""
    out: list[str] = []
    try:
        for prop in ("P279", "P31"):
            data = base.http_get(API, params={"action": "wbgetclaims", "entity": qid,
                                              "property": prop, "format": "json"}, timeout=10).json()
            for c in (data.get("claims") or {}).get(prop, []):
                v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
                if isinstance(v, dict) and v.get("id") and v["id"] not in out:
                    out.append(v["id"])
    except Exception:
        return []
    return out
