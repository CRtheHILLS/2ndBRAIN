import base64
from anthropic import Anthropic
from .config import get_settings

OCR_SYSTEM = """You transcribe ONE book page photographed by its reader. Two jobs matter equally: (1) the printed text, (2) the READER'S OWN MARKS and the page number. Look at the image carefully for faint pen and pencil lines before answering.

Output Markdown in exactly this shape, in the page's own language (Korean or English, keep mixed). Never translate, never summarize.

<page text verbatim; keep paragraph breaks; wrap every passage the reader marked inline as ==...==>

## 표시 목록
- [밑줄] "..."        (pen or pencil underline)
- [형광펜] "..."      (highlighter)
- [별표] "..."        (star or asterisk in the margin next to this passage)
- [괄호] "..."        (bracket or vertical line along the margin)
- [동그라미] "..."    (circled word or phrase)
- [체크] "..."        (check mark next to the passage)
- [기타: <short description>] "..."
## 독자 메모
- <handwritten margin notes, verbatim, with the passage they sit next to if clear>
## 쪽수
<page number, or 모름>

Rules:
- Never invent marks. Only list what is visibly drawn by the reader. If there are none, write exactly "## 표시 목록" followed by "- 없음".
- Distinguish printed emphasis (bold, italic, larger type, quotation styling) from reader marks. Printed emphasis is NOT a mark.
- Faint, thin or light pen/pencil lines count. Look along every line of text and the margins.
- If one mark spans several lines, quote the whole span as one entry.
- Every reader-marked passage must also appear inline in the page text wrapped as ==...==, and every [kind] entry must quote the same words.
- If there is no handwriting, write "## 독자 메모" followed by "- 없음".
- Page number: read the printed number at the top or bottom; write 모름 if not visible.
- Output only this Markdown, nothing else."""

def _client(): return Anthropic(api_key=get_settings().anthropic_api_key)

def _first_text(r) -> str:
    if r.stop_reason == "max_tokens":
        raise RuntimeError("model output truncated")
    return next(b.text for b in r.content if getattr(b, "type", "") == "text")

def ocr_image(image_bytes: bytes, mime: str) -> str:
    r = _client().messages.create(model=get_settings().model_fast, max_tokens=4000, system=OCR_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime,
                                          "data": base64.b64encode(image_bytes).decode()}},
            {"type": "text", "text": "Transcribe this page."}]}])
    return _first_text(r)

def complete(system: str, user: str, smart: bool = False) -> str:
    from .think import complete_text  # lazy: think imports this module
    return complete_text(system, user, smart)[0]
