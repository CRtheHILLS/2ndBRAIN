"""Shared Korean-friendly query tokenizer (search, plan, graph label lookups)."""
import re

_PARTICLES = re.compile(r"(에서는|에게서|이라는|이란|라는|에서|에게|한테|까지|부터|으로|처럼|보다|이랑|하고|랑|"
                        r"을|를|이|가|은|는|의|에|로|와|과|도|만|란)$")
STOPWORDS = {"배우고", "싶어", "이해하고", "알고", "공부하자", "가르쳐", "줘", "나", "저", "완벽히", "확실히",
             "뭐야", "뭐", "뭐가", "거야","뭔가", "무엇", "무엇인가", "어떻게", "왜", "언제", "어디", "누가", "알려줘", "알려",
             "설명해", "설명해줘", "대해", "대해서", "궁금해", "있어", "있나", "하는", "되는", "그리고"}


def tokens(sentence: str) -> list[str]:
    """Words of ``sentence`` without punctuation, trailing particles and stopwords (>= 2 chars, deduped)."""
    out: list[str] = []
    for tok in re.findall(r"\w+", sentence or ""):
        stripped = _PARTICLES.sub("", tok)
        tok = stripped if len(stripped) >= 2 else tok
        if len(tok) >= 2 and tok not in STOPWORDS and tok not in out:
            out.append(tok)
    return out
