"""공부 모드 저장: 노트(.md)를 볼륨 책 '공부모드'에 올리고, 분류하고, 예전 지식과 다리를 놓아요.

사용: PYTHONIOENCODING=utf-8 .venv/Scripts/python -X utf8 .claude/skills/study/study_save.py <노트.md> [--book 공부모드]
주소·토큰은 프로젝트 루트 .env(BRAIN_URL, BRAIN_TOKEN)에서 읽어요. 토큰은 출력하지 않아요.
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]


def load_env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text("utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("note")
    ap.add_argument("--book", default="공부모드")
    ap.add_argument("--no-bridge", action="store_true")
    ns = ap.parse_args()
    note = Path(ns.note)
    env = load_env()
    url, hdr = env["BRAIN_URL"].rstrip("/"), {"X-Brain-Token": env["BRAIN_TOKEN"]}

    with httpx.Client(timeout=600) as c:
        r = c.post(f"{url}/upload", headers=hdr, data={"book": ns.book},
                   files={"file": (note.name, note.read_bytes(), "text/markdown")})
        if r.status_code != 200:
            print(f"업로드 실패 {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return 1
        print("저장:", r.json().get("path"))

        r = c.post(f"{url}/catalog/learn", headers=hdr, params={"book": slug_of(r.json()), "limit": 10})
        if r.status_code == 503:
            print("분류: 나중에 (생각 담당 없음) —", r.json().get("detail", "")[:120])
            return 0
        learned = r.json() if r.status_code == 200 else {}
        print("분류:", json.dumps(learned, ensure_ascii=False)[:600])

        if ns.no_bridge:
            return 0
        r = c.post(f"{url}/graph/rebridge", headers=hdr, params={"limit": 20})
        if r.status_code != 200:
            print(f"다리 놓기 건너뜀 {r.status_code}: {r.text[:160]}")
            return 0
        print(f"새 다리 {r.json().get('bridges', 0)}개 (후보 {r.json().get('targets', 0)}개 살핌)")

        # 새 개념마다 이웃을 보여 줘요: 예전 자료·개념과 어디서 닿았는지 한눈에
        for cid in learned.get("new_concepts", []) or []:
            n = c.get(f"{url}/graph", headers=hdr, params={"center": cid, "depth": 1})
            if n.status_code != 200:
                continue
            nodes = [x for x in n.json().get("nodes", []) if x.get("id") != cid]
            srcs = [x.get("label_ko") or x.get("label_en") for x in nodes if x.get("kind") == "source"]
            cons = [x.get("label_ko") or x.get("label_en") for x in nodes if x.get("kind") == "concept"]
            print(f" · {cid}: 자료 {len(srcs)}개 {srcs[:3]} / 개념 {cons[:6]}")
    return 0


def slug_of(upload_result: dict) -> str:
    return upload_result.get("slug") or "공부모드"


if __name__ == "__main__":
    sys.exit(main())
