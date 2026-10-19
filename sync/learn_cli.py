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
        if isinstance(detail, list):
            detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
        raise RuntimeError(f"서버 응답 {r.status_code}: {detail}")
    try:
        return r.json()
    except ValueError:
        raise RuntimeError("서버 답을 읽지 못했어요. 주소가 맞는지 확인해 주세요.")


def fetch_bytes(path, *, url, token, timeout=120):
    """파일(사진) 하나를 내려받아 바이트로 돌려줘요. (테스트에서는 이 함수를 대체해요)"""
    r = httpx.get(url.rstrip("/") + path, headers={"X-Brain-Token": token}, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"서버 응답 {r.status_code}: 파일을 내려받지 못했어요")
    return r.content


def _env_candidates():
    return [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]


def _read_dotenv():
    """아주 작은 .env 읽기: KEY=VALUE 줄만, 주석·따옴표 무시."""
    vals = {}
    for f in _env_candidates():
        try:
            lines = f.read_text("utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            vals.setdefault(k, v)
    return vals


class _Ctx:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def call(self, method, path, **kw):
        return fetch_json(method, path, url=self.url, token=self.token, **kw)


def _stage_line(stage):
    return f"▶ {STAGE_KO[stage]} ({stage})" if stage in STAGE_KO else f"▶ {stage}"


def _full(ctx, path):
    return path if path.startswith("http") else ctx.url + path


def _report_lines(ctx, q):
    s = q.get("summary") or {}
    out = []
    index = (s.get("pages") or {}).get("index")
    if index:
        out.append(f"지도: {_full(ctx, index)}")
    if s.get("one_line_goal"):
        out.append(f"목표 한 줄: {s['one_line_goal']}")
    if s.get("day1_big_idea"):
        out.append(f"Day 1 핵심: {s['day1_big_idea']}")
    if q.get("status") == "done" or "bridges_top" in s:
        out.append("예전 지식과 이어진 다리:")
        top = s.get("bridges_top") or []
        if top:
            for b in top[:3]:
                out.append(f"  - {b.get('a')} ↔ {b.get('b')} — {b.get('reason', '')}")
        else:
            out.append("  아직 없음")
    if s.get("new_sources"):
        out.append("새로 시도한 출처: " + ", ".join(map(str, s["new_sources"])))
    if "n_sources" in s or "n_concepts" in s:
        out.append(f"자료 {s.get('n_sources', '?')}개 · 개념 {s.get('n_concepts', '?')}개")
    if s.get("cost_estimate") is not None:
        out.append(f"비용 추정: {s['cost_estimate']}")
    if s.get("elapsed_seconds") is not None:
        sec = int(s["elapsed_seconds"])
        out.append(f"걸린 시간: {sec // 60}분 {sec % 60}초" if sec >= 60 else f"걸린 시간: {sec}초")
    return out


def _print_done(ctx, q):
    print("✔ 다 만들었어요!")
    for line in _report_lines(ctx, q):
        print(line)


CONN_LOST = ("✖ 서버에 연결하지 못했어요. 퀘스트는 서버에서 계속 진행돼요. "
             "잠시 뒤 `brain-learn watch {slug}`로 이어 보세요.")


def _watch(ctx, slug, interval):
    last, fails = None, 0
    while True:
        try:
            q = ctx.call("GET", f"/quests/{slug}")
            fails = 0
        except httpx.HTTPError:
            fails += 1
            if fails == 1:
                print("⏳ 서버 연결이 잠깐 끊겼어요. 다시 시도 중…", flush=True)
            if fails >= 5:
                print(CONN_LOST.format(slug=slug))
                return 1
            time.sleep(interval)
            continue
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
    body = {"sentence": ns.sentence}
    if ns.level is not None:  # omitted: the server reads the level from the sentence (기본 초등)
        body["level"] = ns.level
    if ns.days is not None:
        body["days"] = ns.days
    r = ctx.call("POST", "/quests", json_body=body)
    if "slug" not in r:
        print("✖ 서버 답에 퀘스트 이름이 없어요. 서버 버전을 확인해 주세요.", file=sys.stderr)
        return 1
    note = " (이미 있던 퀘스트예요)" if r.get("existing") else ""
    print(f"퀘스트: {r['slug']}{note}")
    url = r.get("url") or f"/site/quests/{r['slug']}/index.html"
    print(f"주소: {_full(ctx, url)}")
    if ns.no_watch:
        return 0
    return _watch(ctx, r["slug"], ns.interval)


def cmd_status(ctx, ns):
    q = ctx.call("GET", f"/quests/{ns.slug}")
    if ns.json:
        print(json.dumps(q, ensure_ascii=False, indent=2))
        return 0
    s = q.get("summary") or {}
    print(f"{ns.slug}: {q.get('status')}" + (f" · {STAGE_KO.get(s.get('stage'), s.get('stage'))}" if s.get("stage") else ""))
    if q.get("error"):
        print(f"사유: {q['error']}")
    if q.get("open_tasks"):
        print(f"대기 중인 과제: {q['open_tasks']}개")
    for line in _report_lines(ctx, q):
        print(line)
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


_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/heic": ".heic", "image/heif": ".heif", "application/pdf": ".pdf"}


def cmd_ocr_list(ctx, ns):
    rows = ctx.call("GET", "/ocr/pending")
    if not rows:
        print("읽어 줄 사진이 없어요.")
        return 0
    print(f"{'id':<14} {'책':<20} {'파일':<28} 올린 때")
    for r in rows:
        print(f"{r.get('id', '')[:12]:<14} {r.get('book', ''):<20} {r.get('file', ''):<28} "
              f"{str(r.get('added_at', ''))[:16]}")
    return 0


def _resolve_ocr_id(ctx, prefix):
    rows = ctx.call("GET", "/ocr/pending")
    hits = [r for r in rows if r.get("id", "").startswith(prefix)]
    if len(hits) != 1:
        raise RuntimeError("그 번호의 대기 항목을 찾지 못했어요" if not hits else "번호가 여러 개와 맞아요. 더 길게 써 주세요")
    return hits[0]


def cmd_ocr_get(ctx, ns):
    entry = _resolve_ocr_id(ctx, ns.id)
    content = fetch_bytes(f"/ocr/file/{entry['id']}", url=ctx.url, token=ctx.token)
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    ext = Path(entry.get("file", "")).suffix or _EXT.get(entry.get("mime", ""), ".bin")
    img = out / f"{entry['id']}{ext}"
    img.write_bytes(content)
    txt = out / f"{entry['id']}.txt"
    txt.write_text(f"(이 파일에 읽은 글자를 적고 `brain-learn ocr submit {entry['id']} {txt.name}`로 제출해요. "
                   "이 안내 줄은 지워도 돼요.)\n", encoding="utf-8")
    print(f"저장했어요: {img}\n글자를 적을 파일: {txt}")
    return 0


def cmd_ocr_submit(ctx, ns):
    try:
        text = Path(ns.file).read_text("utf-8")
    except OSError as e:
        print(f"파일을 읽지 못했어요: {e}", file=sys.stderr)
        return 2
    entry = _resolve_ocr_id(ctx, ns.id)
    r = ctx.call("POST", f"/ocr/{entry['id']}", json_body={"text": text})
    print(f"받았어요 ({r.get('book')} / {r.get('file')}). 학습 대기열에 올렸어요.")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="brain-learn", description="한 문장으로 배우기 — 학습 퀘스트 도구")
    p.add_argument("--url", default=None, help="서버 주소 (명령 앞에 써요. 기본: BRAIN_URL 환경변수 또는 .env)")
    p.add_argument("--token", default=None, help="접근 토큰 (명령 앞에 써요. 기본: BRAIN_TOKEN 환경변수 또는 .env)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="명령")

    s = sub.add_parser("start", help="새 퀘스트를 시작하고 끝날 때까지 지켜봐요", description="새 퀘스트를 시작해요.")
    s.add_argument("sentence", help='배우고 싶은 것 한 문장 (예: "헬리콥터 운전 배우고 싶어")')
    s.add_argument("--days", type=int, default=None, help="공부할 일수 (기본: 서버 기본값 7일)")
    s.add_argument("--level", choices=["초등", "일반", "전문"], default=None,
                   help="눈높이 (기본: 문장에서 읽고, 없으면 초등)")
    s.add_argument("--no-watch", action="store_true", help="시작만 하고 지켜보지 않아요")
    s.add_argument("--interval", type=float, default=10, help="진행 확인 간격(초), 기본 10")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("status", help="퀘스트 상태를 한 번 확인해요")
    s.add_argument("slug", help="퀘스트 이름(slug)")
    s.add_argument("--json", action="store_true", help="퀘스트 원본 정보를 JSON으로 그대로 출력해요")
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

    s = sub.add_parser("ocr", help="사진 글자 읽기 대기열 (list · get · submit)")
    osub = s.add_subparsers(dest="ocr_cmd", required=True, metavar="하위명령")
    o = osub.add_parser("list", help="읽어 줄 사진 목록")
    o.set_defaults(fn=cmd_ocr_list)
    o = osub.add_parser("get", help="사진을 내려받고 글자를 적을 txt를 만들어요")
    o.add_argument("id", help="항목 번호(앞 몇 글자만 써도 돼요)")
    o.add_argument("--out", required=True, help="저장할 폴더")
    o.set_defaults(fn=cmd_ocr_get)
    o = osub.add_parser("submit", help="읽은 글자(txt 파일)를 제출해요")
    o.add_argument("id", help="항목 번호(앞 몇 글자만 써도 돼요)")
    o.add_argument("file", help="글자가 들어 있는 txt 파일")
    o.set_defaults(fn=cmd_ocr_submit)
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
    dotenv = _read_dotenv()
    url = ns.url or os.environ.get("BRAIN_URL") or dotenv.get("BRAIN_URL")
    token = ns.token or os.environ.get("BRAIN_TOKEN") or dotenv.get("BRAIN_TOKEN")
    if not url or not token:
        print("서버 주소와 토큰이 필요해요. --url/--token 옵션을 쓰거나 "
              "환경변수 BRAIN_URL, BRAIN_TOKEN을 설정해 주세요.", file=sys.stderr)
        return 2
    try:
        return ns.fn(_Ctx(url, token), ns)
    except RuntimeError as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    except (httpx.HTTPError, httpx.InvalidURL):
        print("✖ 서버에 연결하지 못했어요. 주소와 인터넷 연결을 확인하고, 퀘스트가 있다면 "
              "잠시 뒤 `brain-learn watch <slug>`로 이어 보세요.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했어요. 퀘스트는 서버에서 계속 진행돼요.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
