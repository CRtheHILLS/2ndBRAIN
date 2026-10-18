"""brain-learn — 한 문장으로 배우는 학습 퀘스트 CLI.

종료 코드: 0 완료 / 1 실패 / 2 사용법 오류 / 3 생각 담당 대기.
"""
import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

STAGE_KO = {
    "plan": "계획 세우는 중",
    "collect": "자료 모으는 중",
    "classify": "자료 분류·그래프 연결 중",
    "teach": "수업 만드는 중",
    "bridge": "예전 지식과 잇는 중",
    "archive": "보관·색인 중",
}

TASKS_README = """# 생각 담당 과제

이 폴더의 과제는 서버가 직접 풀지 못해서 기다리고 있는 일이에요.

- `<task_id>.prompt.md` : 읽기 좋게 정리한 지시문 (System / User)
- `<task_id>.json` : 서버가 준 원본 과제

## 제출 방법

1. 각 `.prompt.md`를 읽고, 요구한 스키마에 맞는 JSON 객체 하나만 만들어요. 설명 글은 붙이지 않아요.
2. 그 JSON을 파일로 저장해요. 예: `<task_id>.out.json`
3. 제출해요.

```
brain-learn submit <slug> <task_id> <task_id>.out.json
```

4. 다 제출했으면 `brain-learn watch <slug>`로 이어서 지켜봐요.
"""


def fetch_json(method, path, *, url, token, json_body=None, params=None, timeout=60):
    """서버에 요청 한 번 보내고 JSON을 돌려줘요. (테스트에서는 이 함수를 대체해요)"""
    r = httpx.request(method, url.rstrip("/") + path, headers={"X-Brain-Token": token},
                      json=json_body, params=params, timeout=timeout)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(f"서버가 {r.status_code}로 답했어요: {detail}")
    return r.json()


class _Ctx:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def call(self, method, path, **kw):
        return fetch_json(method, path, url=self.url, token=self.token, **kw)


def _stage_line(stage):
    return f"▶ {STAGE_KO[stage]} ({stage})" if stage in STAGE_KO else f"▶ {stage}"


def _full(ctx, path):
    return path if path.startswith("http") else ctx.url + path


def _print_done(ctx, q):
    s = q.get("summary") or {}
    index = (s.get("pages") or {}).get("index")
    print("✔ 다 만들었어요!")
    if index:
        print(f"지도: {_full(ctx, index)}")
    print(f"자료 {s.get('n_sources', '?')}개 · 개념 {s.get('n_concepts', '?')}개 · "
          f"예전 지식과 이어진 다리 {s.get('bridges', 0)}개")
    if s.get("cost_estimate") is not None:
        print(f"비용 추정: {s['cost_estimate']}")


def _watch(ctx, slug, interval):
    last = None
    while True:
        q = ctx.call("GET", f"/quests/{slug}")
        status, s = q.get("status"), q.get("summary") or {}
        stage = s.get("stage")
        if status == "done":
            _print_done(ctx, q)
            return 0
        if status == "failed":
            print(f"✖ 중간에 멈췄어요: {q.get('error') or '이유를 알 수 없어요'}")
            print(f"다시 시도하려면: brain-learn resume {slug}")
            return 1
        if status == "waiting_thinker":
            print("⏸ 생각 담당이 필요해요: brain-learn tasks "
                  f"{slug} --out <dir>")
            return 3
        if stage and stage != last:
            print(_stage_line(stage), flush=True)
            last = stage
        time.sleep(interval)


def cmd_start(ctx, ns):
    r = ctx.call("POST", "/quests", json_body={"sentence": ns.sentence, "days": ns.days, "level": ns.level})
    note = " (이미 있던 퀘스트예요)" if r.get("existing") else ""
    print(f"퀘스트: {r['slug']}{note}")
    print(f"주소: {_full(ctx, r['url'])}")
    if ns.no_watch:
        return 0
    return _watch(ctx, r["slug"], ns.interval)


def cmd_status(ctx, ns):
    q = ctx.call("GET", f"/quests/{ns.slug}")
    s = q.get("summary") or {}
    print(f"{ns.slug}: {q.get('status')}" + (f" · {STAGE_KO.get(s.get('stage'), s.get('stage'))}" if s.get("stage") else ""))
    if q.get("error"):
        print(f"사유: {q['error']}")
    if q.get("open_tasks"):
        print(f"대기 중인 과제: {q['open_tasks']}개")
    return 0


def cmd_watch(ctx, ns):
    return _watch(ctx, ns.slug, ns.interval)


def cmd_tasks(ctx, ns):
    tasks = ctx.call("GET", f"/quests/{ns.slug}/tasks")
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    for t in tasks:
        tid = t["task_id"]
        (out / f"{tid}.json").write_text(json.dumps(t, ensure_ascii=False, indent=2), "utf-8")
        md = (f"# 과제 {tid} ({t.get('kind')} → {t.get('schema')})\n\n"
              f"## System\n\n{t.get('system', '')}\n\n## User\n\n{t.get('user', '')}\n")
        (out / f"{tid}.prompt.md").write_text(md, "utf-8")
    (out / "README.md").write_text(TASKS_README, "utf-8")
    print(f"과제 {len(tasks)}개를 {out} 에 저장했어요.")
    for t in tasks:
        print(f"  - {t['task_id']} ({t.get('kind')})")
    return 0


def cmd_submit(ctx, ns):
    try:
        data = json.loads(Path(ns.file).read_text("utf-8"))
    except (OSError, ValueError) as e:
        print(f"파일을 읽지 못했어요: {e}", file=sys.stderr)
        return 2
    if isinstance(data, dict) and set(data) == {"output"} and isinstance(data["output"], dict):
        data = data["output"]
    r = ctx.call("POST", f"/quests/{ns.slug}/tasks/{ns.task_id}", json_body={"output": data})
    print(f"받았어요 (상태: {r.get('status')})")
    return 0


def cmd_list(ctx, ns):
    rows = ctx.call("GET", "/quests")
    if not rows:
        print("아직 퀘스트가 없어요.")
        return 0
    print(f"{'slug':<28} {'상태':<16} {'단계':<10} 만든 날")
    for q in rows:
        stage = (q.get("summary") or {}).get("stage") or "-"
        print(f"{q.get('slug', ''):<28} {q.get('status', ''):<16} {stage:<10} {str(q.get('created_at', ''))[:10]}")
    return 0


def cmd_resume(ctx, ns):
    q = ctx.call("POST", f"/quests/{ns.slug}/resume")
    print(f"다시 시작했어요 (상태: {q.get('status')}). 지켜보려면: brain-learn watch {ns.slug}")
    return 0


def cmd_rerender(ctx, ns):
    q = ctx.call("POST", f"/quests/{ns.slug}/rerender", params={"level": ns.level})
    print(f"{ns.level} 눈높이로 다시 만들어요 (상태: {q.get('status')}).")
    return 0


def _plain(h):
    t = re.sub(r"<(br|/p|/li|/h\d|/div)\s*/?>", "\n", h or "")
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(t)).strip()


def cmd_ask(ctx, ns):
    r = ctx.call("POST", "/ask", json_body={"q": ns.question, "mode": ns.mode, "level": ns.level})
    print(_plain(r.get("answer_html", "")))
    cites = r.get("citations") or []
    if cites:
        print("\n출처:")
        for c in cites:
            print(f"  - {c.get('title')}  {_full(ctx, c['url']) if c.get('url') else ''}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="brain-learn", description="한 문장으로 배우기 — 학습 퀘스트 도구")
    p.add_argument("--url", default=None, help="서버 주소 (기본: 환경변수 BRAIN_URL)")
    p.add_argument("--token", default=None, help="접근 토큰 (기본: 환경변수 BRAIN_TOKEN)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="명령")

    s = sub.add_parser("start", help="새 퀘스트를 시작하고 끝날 때까지 지켜봐요", description="새 퀘스트를 시작해요.")
    s.add_argument("sentence", help='배우고 싶은 것 한 문장 (예: "헬리콥터 운전 배우고 싶어")')
    s.add_argument("--days", type=int, default=None, help="공부할 일수 (기본: 서버 기본값 7일)")
    s.add_argument("--level", choices=["초등", "일반", "전문"], default="초등", help="눈높이 (기본: 초등)")
    s.add_argument("--no-watch", action="store_true", help="시작만 하고 지켜보지 않아요")
    s.add_argument("--interval", type=float, default=10, help="진행 확인 간격(초), 기본 10")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("status", help="퀘스트 상태를 한 번 확인해요")
    s.add_argument("slug", help="퀘스트 이름(slug)")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("watch", help="끝날 때까지 진행 상황을 지켜봐요 (완료 0 · 실패 1 · 생각 담당 필요 3)")
    s.add_argument("slug", help="퀘스트 이름(slug)")
    s.add_argument("--interval", type=float, default=10, help="진행 확인 간격(초), 기본 10")
    s.set_defaults(fn=cmd_watch)

    s = sub.add_parser("tasks", help="기다리는 생각 과제를 파일로 내려받아요")
    s.add_argument("slug", help="퀘스트 이름(slug)")
    s.add_argument("--out", required=True, help="과제 파일을 저장할 폴더")
    s.set_defaults(fn=cmd_tasks)

    s = sub.add_parser("submit", help="과제 답(JSON 파일)을 제출해요")
    s.add_argument("slug", help="퀘스트 이름(slug)")
    s.add_argument("task_id", help="과제 번호")
    s.add_argument("file", help="답이 들어 있는 JSON 파일")
    s.set_defaults(fn=cmd_submit)

    s = sub.add_parser("list", help="퀘스트 목록을 보여줘요")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("resume", help="멈춘 퀘스트를 다시 시작해요")
    s.add_argument("slug", help="퀘스트 이름(slug)")
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("rerender", help="다른 눈높이로 페이지를 다시 만들어요")
    s.add_argument("slug", help="퀘스트 이름(slug)")
    s.add_argument("--level", choices=["초등", "일반", "전문"], default="일반", help="눈높이 (기본: 일반)")
    s.set_defaults(fn=cmd_rerender)

    s = sub.add_parser("ask", help="내 지식 창고(없으면 웹)에서 질문에 답해요")
    s.add_argument("question", help="질문")
    s.add_argument("--mode", choices=["auto", "vault", "web"], default="auto", help="찾는 곳 (기본: auto)")
    s.add_argument("--level", choices=["초등", "일반", "전문"], default="초등", help="눈높이 (기본: 초등)")
    s.set_defaults(fn=cmd_ask)
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = build_parser()
    try:
        ns = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    url = ns.url or os.environ.get("BRAIN_URL")
    token = ns.token or os.environ.get("BRAIN_TOKEN")
    if not url or not token:
        print("서버 주소와 토큰이 필요해요. --url/--token 옵션을 쓰거나 "
              "환경변수 BRAIN_URL, BRAIN_TOKEN을 설정해 주세요.", file=sys.stderr)
        return 2
    try:
        return ns.fn(_Ctx(url, token), ns)
    except (RuntimeError, httpx.HTTPError) as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했어요. 퀘스트는 서버에서 계속 진행돼요.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
