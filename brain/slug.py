import re
import unicodedata


def slugify(title: str) -> str:
    t = unicodedata.normalize("NFC", title).lower()
    t = re.sub(r"[^0-9a-z가-힣]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-")
    return t[:60].rstrip("-")
