"""Parse the marks-aware page transcription (see ``llm.OCR_SYSTEM``).

Shape: page text with ``==marked==`` spans, then ``## 표시 목록`` / ``## 독자 메모`` / ``## 쪽수``.
Every function tolerates missing sections (legacy bodies only have ``==..==``).
"""
import re

_SPAN = re.compile(r"==(.+?)==", re.S)
_HEAD = re.compile(r"^##\s*(표시 목록|독자 메모|쪽수)\s*$", re.M)
_HAS_LIST = re.compile(r"^##\s*표시 목록\s*$", re.M)
_MARK = re.compile(r"^\s*[-*]\s*\[(?P<kind>[^\]]+)\]\s*(?P<text>.*)$")
_NONE = {"없음", "none", "-", ""}


def _norm(s: str) -> str:
    return " ".join(s.split())


def _sections(body: str) -> dict[str, str]:
    heads = list(_HEAD.finditer(body))
    out = {"text": body[:heads[0].start()] if heads else body}
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        out[h.group(1)] = body[h.end():end].strip()
    return out


def _unquote(t: str) -> str:
    t = t.strip()
    if len(t) >= 2 and t[0] in "\"“'「" and t[-1] in "\"”'」":
        t = t[1:-1]
    return _norm(t)


def parse_marks(md_body: str) -> dict:
    sec = _sections(md_body or "")
    marks = []
    for line in sec.get("표시 목록", "").splitlines():
        m = _MARK.match(line)
        if m and _unquote(m["text"]):
            marks.append({"kind": _norm(m["kind"]), "text": _unquote(m["text"])})
    notes = []
    for line in sec.get("독자 메모", "").splitlines():
        t = re.sub(r"^\s*[-*]\s*", "", line).strip()
        if t and t.lower() not in _NONE:
            notes.append(t)
    lines = sec.get("쪽수", "").strip().splitlines()
    page = _norm(lines[0]) if lines else ""
    spans = [_norm(s) for s in _SPAN.findall(sec["text"]) if s.strip()]
    return {"marks": marks, "notes": notes,
            "page": None if page in ("", "모름") else page, "underline_spans": spans}


def count_marks(md_body: str) -> int:
    p = parse_marks(md_body or "")
    return len(p["marks"]) if _HAS_LIST.search(md_body or "") else len(p["underline_spans"])


def mark_lines(md_body: str) -> list[str]:
    """Display lines for CR: ``[kind] text`` per mark; legacy bodies give ``[밑줄] span``."""
    p = parse_marks(md_body or "")
    if _HAS_LIST.search(md_body or ""):
        return [f"[{m['kind']}] {m['text']}" for m in p["marks"]]
    return [f"[밑줄] {s}" for s in p["underline_spans"]]
