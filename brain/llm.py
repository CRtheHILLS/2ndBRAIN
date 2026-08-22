import base64
from anthropic import Anthropic
from .config import get_settings

OCR_SYSTEM = ("You transcribe book pages photographed by the reader. Output the page text verbatim "
  "in its original language (Korean or English, keep mixed). Wrap underlined or highlighted passages "
  "in ==double equals==. Put the reader's handwritten margin notes at the end under '## 독자 메모'. "
  "Do not summarize. Do not translate.")

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
    s = get_settings()
    r = _client().messages.create(model=s.model_smart if smart else s.model_fast, max_tokens=8000,
        system=system, messages=[{"role": "user", "content": user}])
    return _first_text(r)
