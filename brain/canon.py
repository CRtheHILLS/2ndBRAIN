"""Concept canonicalization: one permanent node id per concept, however a source spells it."""
import re
import unicodedata

from . import frame, graph
from .config import get_settings
from .connectors import wikidata
from .slug import slugify

_BRACKETS = re.compile(r"^(.*?)\s*[(（\[]([^()（）\[\]]+)[)）\]]\s*$")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "")).strip().lower()


def _ascii_dominant(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) > 0.8


def split_bilingual(label: str) -> tuple[str, str]:
    """'양자 얽힘 (Quantum Entanglement)' -> ('양자 얽힘', 'Quantum Entanglement')."""
    label = unicodedata.normalize("NFC", label or "").strip()
    m = _BRACKETS.match(label)
    if m and m.group(1).strip() and _ascii_dominant(m.group(2)):
        return m.group(1).strip(), m.group(2).strip()
    return label, ""


def concept_id(label_en: str, label_ko: str, suffix: str = "") -> str:
    base = slugify(label_en) or slugify(label_ko)
    return f"{base}-{suffix.lower()}" if base and suffix else base


def _area(code: str) -> str:
    return "" if not code or code == frame.FALLBACK_CODE else frame.area_of(code)


def _existing(label_ko: str, label_en: str) -> dict | None:
    labels = [x for x in (label_ko, label_en) if x]
    for lab in labels:
        if (nid := graph.find_alias(lab)) and (n := graph.get_node(nid)):
            return n
    for lab in labels:
        for n in graph.search_labels(lab, limit=10):
            if n["kind"] == "concept" and norm(lab) in (norm(n["label_ko"]), norm(n["label_en"])):
                return n
    return None


def _lookup(label_ko: str, label_en: str, lookup) -> dict | None:
    fn = lookup or (wikidata.search_entity if get_settings().canon_wikidata else None)
    if fn is None:
        return None
    for lab, lang in ((label_ko, "ko"), (label_en, "en")):
        if not lab:
            continue
        try:
            hit = fn(lab, lang)
        except Exception:
            hit = None
        if hit and hit.get("id"):
            return hit
    return None


def _learn(nid: str, *labels: str) -> str:
    for lab in labels:
        if lab:
            graph.add_alias(lab, nid)
    return graph.resolve(nid)


def canon(label_ko: str, label_en: str = "", field_code: str = "", *, lookup=None) -> str:
    if not label_en:
        label_ko, label_en = split_bilingual(label_ko)
    label_ko, label_en = label_ko.strip(), label_en.strip()
    area = _area(field_code)

    found = _existing(label_ko, label_en)
    hit = None
    if found:
        node_area = _area(found["field_code"])
        if not (area and node_area and area != node_area):
            return _learn(found["id"], label_ko, label_en)
        # same spelling in a different field: only differing Wikidata ids prove a homonym
        hit = _lookup(label_ko, label_en, lookup)
        if not (hit and found["wikidata"] and hit["id"] != found["wikidata"]):
            return _learn(found["id"], label_ko, label_en)
    else:
        hit = _lookup(label_ko, label_en, lookup)
    qid = hit["id"] if hit else ""

    if qid and (nid := graph.find_alias(f"wd:{qid}")):
        return _learn(nid, label_ko, label_en)

    base_id = concept_id(label_en, label_ko)
    if not base_id:
        raise ValueError("empty concept label")
    cid = base_id
    ex = graph.get_node(base_id)
    if ex:
        qid_clash = bool(qid and ex["wikidata"] and qid != ex["wikidata"])
        a = _area(ex["field_code"])
        if qid_clash or (a and area and a != area):
            cid = concept_id(label_en, label_ko, suffix=field_code)
    graph.upsert_node(cid, "concept", label_ko, label_en, wikidata=qid, field_code=field_code)
    if hit and hit.get("label") and norm(hit["label"]) != norm(label_en):
        graph.add_alias(hit["label"], cid)
    return graph.resolve(cid)
