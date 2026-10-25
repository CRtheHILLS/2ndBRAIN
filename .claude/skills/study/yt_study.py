"""공부 모드 — 유튜브 자막 전체 받기.

사용: PYTHONIOENCODING=utf-8 .venv/Scripts/python -X utf8 .claude/skills/study/yt_study.py "<유튜브 링크>" [--out 폴더]
결과: <out>/yt-<영상id>.md 에 제목·채널·길이·자막 전체(1분 단위 시간표)를 저장하고 한 줄 요약을 출력해요.
자막 우선순위: 한국어(수동) → 영어(수동) → 자동 생성(한국어 → 영어 → 아무 언어).
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from youtube_transcript_api import YouTubeTranscriptApi

ROOT = Path(__file__).resolve().parents[3]


def video_id(url: str) -> str | None:
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if p.path == "/watch":
            return (parse_qs(p.query).get("v") or [None])[0]
        m = re.match(r"/(?:shorts|live|embed)/([\w-]+)", p.path)
        return m.group(1) if m else None
    if host == "youtu.be":
        return p.path.strip("/").split("/")[0] or None
    return None


def pick_transcript(vid: str):
    tl = YouTubeTranscriptApi().list(vid)
    for finder, langs in ((tl.find_manually_created_transcript, ["ko"]),
                          (tl.find_manually_created_transcript, ["en"]),
                          (tl.find_generated_transcript, ["ko"]),
                          (tl.find_generated_transcript, ["en"])):
        try:
            return finder(langs).fetch()
        except Exception:
            continue
    for t in tl:  # 아무 언어라도
        try:
            return t.fetch()
        except Exception:
            continue
    return None


def meta(url: str) -> dict:
    try:
        r = httpx.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=15)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def mmss(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default=str(ROOT / ".omc" / "study"))
    ns = ap.parse_args()
    vid = video_id(ns.url)
    if not vid:
        print("유튜브 링크가 아니에요:", ns.url, file=sys.stderr)
        return 2
    tr = pick_transcript(vid)
    if tr is None:
        print("이 영상에는 받을 수 있는 자막이 없어요. (youtube-downloader로 소리를 받아 받아쓰기할지 CR에게 물어보세요)", file=sys.stderr)
        return 1
    snippets = list(tr.snippets)
    m = meta(ns.url)
    title = m.get("title") or f"유튜브 {vid}"
    channel = m.get("author_name") or "?"
    total = (snippets[-1].start + snippets[-1].duration) if snippets else 0.0

    # 1분 단위 덩어리
    blocks: list[tuple[int, list[str]]] = []
    for s in snippets:
        minute = int(s.start // 60)
        text = s.text.replace("\n", " ").strip()
        if not text:
            continue
        if blocks and blocks[-1][0] == minute:
            blocks[-1][1].append(text)
        else:
            blocks.append((minute, [text]))
    body = "\n".join(f"[{mmss(mn * 60)}] " + " ".join(parts) for mn, parts in blocks)
    chars = sum(len(" ".join(parts)) for _, parts in blocks)

    out_dir = Path(ns.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"yt-{vid}.md"
    out.write_text(
        f"# {title}\n\n"
        f"- 공부 모드 · 유튜브 자막 전체 · 채널: {channel} · 링크: https://www.youtube.com/watch?v={vid}\n"
        f"- 길이: {mmss(total)} · 자막 언어: {tr.language_code} · 자동 생성: {'예' if tr.is_generated else '아니요'} · 글자 수: {chars:,}\n"
        f"- 태그: #유튜브 #공부모드\n\n"
        f"## 자막 전체 (1분 단위)\n{body}\n",
        "utf-8")
    print(json.dumps({"path": str(out), "title": title, "channel": channel, "length": mmss(total),
                      "lang": tr.language_code, "generated": tr.is_generated, "chars": chars,
                      "blocks": len(blocks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
