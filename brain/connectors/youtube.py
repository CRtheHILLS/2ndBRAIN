from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from youtube_transcript_api import YouTubeTranscriptApi

from .base import Candidate, Doc


def video_id(url: str) -> str | None:
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if p.path == "/watch":
            return (parse_qs(p.query).get("v") or [None])[0]
        m = re.match(r"/shorts/([\w-]+)", p.path)
        return m.group(1) if m else None
    if host == "youtu.be":
        return p.path.strip("/").split("/")[0] or None
    return None


def fetch(c: Candidate) -> Doc | None:
    vid = video_id(c.url)
    if not vid:
        return None
    try:
        tr = YouTubeTranscriptApi().fetch(vid, languages=["ko", "en"])
        text = " ".join(s.text for s in tr.snippets).strip()
        lang = tr.language_code
    except Exception:
        return None
    if not text:
        return None
    return Doc(url=c.url, title=c.title, text=text, lang=lang, kind="video", connector="youtube")


class YouTubeConnector:
    name = "youtube"

    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        return []

    def fetch(self, c: Candidate) -> Doc | None:
        return fetch(c)
