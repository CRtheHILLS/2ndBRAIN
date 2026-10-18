import json

import pytest

from sync import learn_cli


def _fake(calls, responses):
    def fetch(method, path, *, url, token, json_body=None, params=None, timeout=60):
        calls.append((method, path, url, token, json_body, params))
        r = responses[(method, path)]
        if isinstance(r, list) and r and isinstance(r[0], dict) and "status" in r[0] and len(r) > 1:
            return r.pop(0)
        if isinstance(r, list) and len(r) == 1 and isinstance(r[0], dict) and "status" in r[0]:
            return r[0]
        return r
    return fetch


BASE = ["--url", "http://x", "--token", "t"]


def test_start_posts_and_prints_url(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(learn_cli, "fetch_json", _fake(calls, {
        ("POST", "/quests"): {"slug": "heli", "status": "queued", "existing": False,
                              "url": "/site/quests/heli/index.html"}}))
    code = learn_cli.main(BASE + ["start", "헬리콥터 배우고 싶어", "--days", "5", "--level", "일반", "--no-watch"])
    out = capsys.readouterr().out
    assert code == 0
    assert "heli" in out and "http://x/site/quests/heli/index.html" in out
    assert calls[0][4] == {"sentence": "헬리콥터 배우고 싶어", "days": 5, "level": "일반"}
    assert calls[0][3] == "t"


def test_watch_exits_3_on_waiting_and_prints_hint(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(learn_cli, "fetch_json", _fake(calls, {
        ("GET", "/quests/heli"): [
            {"status": "running", "summary": {"stage": "collect"}},
            {"status": "waiting_thinker", "summary": {"stage": "plan", "waiting_task": "t1"}}]}))
    code = learn_cli.main(BASE + ["watch", "heli", "--interval", "0"])
    out = capsys.readouterr().out
    assert code == 3
    assert "▶ 자료 모으는 중 (collect)" in out
    assert "⏸ 생각 담당이 필요해요: brain-learn tasks heli --out" in out


def test_watch_exits_0_on_done_prints_link(monkeypatch, capsys):
    done = {"status": "done", "summary": {
        "stage": "archive", "pages": {"index": "/site/quests/heli/index.html", "days": []},
        "n_sources": 12, "n_concepts": 30, "bridges": 2, "cost_estimate": "$0.40"}}
    monkeypatch.setattr(learn_cli, "fetch_json", _fake([], {("GET", "/quests/heli"): done}))
    code = learn_cli.main(BASE + ["watch", "heli", "--interval", "0"])
    out = capsys.readouterr().out
    assert code == 0
    assert "http://x/site/quests/heli/index.html" in out
    assert "12" in out and "$0.40" in out


def test_watch_exits_1_on_failed(monkeypatch, capsys):
    monkeypatch.setattr(learn_cli, "fetch_json", _fake([], {
        ("GET", "/quests/heli"): {"status": "failed", "error": "자료가 없어요", "summary": {}}}))
    assert learn_cli.main(BASE + ["watch", "heli", "--interval", "0"]) == 1
    assert "자료가 없어요" in capsys.readouterr().out


def test_tasks_writes_prompt_files(monkeypatch, tmp_path, capsys):
    task = {"task_id": "t1", "kind": "plan", "schema": "PlanOut", "system": "SYS 내용",
            "user": "USER 내용", "context": {}, "created_at": "x", "error": None}
    monkeypatch.setattr(learn_cli, "fetch_json", _fake([], {("GET", "/quests/heli/tasks"): [task]}))
    out_dir = tmp_path / "o"
    assert learn_cli.main(BASE + ["tasks", "heli", "--out", str(out_dir)]) == 0
    assert json.loads((out_dir / "t1.json").read_text("utf-8"))["kind"] == "plan"
    md = (out_dir / "t1.prompt.md").read_text("utf-8")
    assert "# 과제 t1 (plan → PlanOut)" in md and "## System" in md and "## User" in md
    assert "SYS 내용" in md and "USER 내용" in md
    assert "submit" in (out_dir / "README.md").read_text("utf-8")


@pytest.mark.parametrize("payload", [{"goal": "g"}, {"output": {"goal": "g"}}])
def test_submit_reads_file_and_posts(monkeypatch, tmp_path, capsys, payload):
    calls = []
    monkeypatch.setattr(learn_cli, "fetch_json", _fake(calls, {
        ("POST", "/quests/heli/tasks/t1"): {"accepted": True, "status": "running"}}))
    f = tmp_path / "t1.out.json"
    f.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    assert learn_cli.main(BASE + ["submit", "heli", "t1", str(f)]) == 0
    assert calls[0][4] == {"output": {"goal": "g"}}


def test_env_defaults_for_url_token(monkeypatch, capsys):
    calls = []
    monkeypatch.setenv("BRAIN_URL", "http://env")
    monkeypatch.setenv("BRAIN_TOKEN", "envtok")
    monkeypatch.setattr(learn_cli, "fetch_json", _fake(calls, {("GET", "/quests"): []}))
    assert learn_cli.main(["list"]) == 0
    assert calls[0][2] == "http://env" and calls[0][3] == "envtok"


def test_missing_url_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("BRAIN_URL", raising=False)
    monkeypatch.delenv("BRAIN_TOKEN", raising=False)
    assert learn_cli.main(["list"]) == 2
    assert "BRAIN_URL" in capsys.readouterr().err


def test_list_and_ask(monkeypatch, capsys):
    monkeypatch.setattr(learn_cli, "fetch_json", _fake([], {
        ("GET", "/quests"): [],
        ("POST", "/ask"): {"answer_html": "<p>안녕 <b>CR</b></p>", "citations": []}}))
    assert learn_cli.main(BASE + ["list"]) == 0
    assert learn_cli.main(BASE + ["ask", "질문"]) == 0
    assert "안녕 CR" in capsys.readouterr().out


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    monkeypatch.setattr(learn_cli, "_env_candidates", lambda: [])


def test_done_prints_full_report(monkeypatch, capsys):
    done = {"status": "done", "summary": {
        "pages": {"index": "/site/quests/heli/index.html", "days": []},
        "one_line_goal": "헬기를 띄우는 원리 알기", "day1_big_idea": "날개가 돌며 공기를 눌러요",
        "bridges_top": [{"a": "베르누이", "b": "양력", "reason": "공기 흐름"}],
        "new_sources": ["youtube"], "n_sources": 3, "n_concepts": 4, "bridges": 1,
        "cost_estimate": "$0.40", "elapsed_seconds": 125}}
    monkeypatch.setattr(learn_cli, "fetch_json", _fake([], {("GET", "/quests/heli"): done}))
    assert learn_cli.main(BASE + ["status", "heli"]) == 0
    out = capsys.readouterr().out
    for t in ["목표 한 줄: 헬기를 띄우는 원리 알기", "Day 1 핵심: 날개가", "베르누이 ↔ 양력 — 공기 흐름",
              "새로 시도한 출처: youtube", "비용 추정: $0.40", "걸린 시간: 2분 5초"]:
        assert t in out
    done["summary"]["bridges_top"] = []
    assert learn_cli.main(BASE + ["watch", "heli", "--interval", "0"]) == 0
    assert "아직 없음" in capsys.readouterr().out
    assert learn_cli.main(BASE + ["status", "heli", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "done"


def test_watch_retries_connect_errors(monkeypatch, capsys):
    import httpx
    n = {"i": 0}

    def fetch(method, path, **kw):
        n["i"] += 1
        if n["i"] <= 2:
            raise httpx.ConnectError("x")
        return {"status": "done", "summary": {}}
    monkeypatch.setattr(learn_cli, "fetch_json", fetch)
    assert learn_cli.main(BASE + ["watch", "heli", "--interval", "0"]) == 0
    assert "서버 연결이 잠깐 끊겼어요" in capsys.readouterr().out


def test_watch_gives_up_after_5(monkeypatch, capsys):
    import httpx

    def fetch(method, path, **kw):
        raise httpx.ConnectError("x")
    monkeypatch.setattr(learn_cli, "fetch_json", fetch)
    assert learn_cli.main(BASE + ["watch", "heli", "--interval", "0"]) == 1
    assert "서버에 연결하지 못했어요" in capsys.readouterr().out


def test_dotenv_is_loaded(monkeypatch, tmp_path):
    calls = []
    (tmp_path / ".env").write_text('# c\nBRAIN_URL="http://dot"\nBRAIN_TOKEN=dtok\n', "utf-8")
    monkeypatch.delenv("BRAIN_URL", raising=False)
    monkeypatch.delenv("BRAIN_TOKEN", raising=False)
    monkeypatch.setattr(learn_cli, "_env_candidates", lambda: [tmp_path / ".env"])
    monkeypatch.setattr(learn_cli, "fetch_json", _fake(calls, {("GET", "/quests"): []}))
    assert learn_cli.main(["list"]) == 0
    assert calls[0][2] == "http://dot" and calls[0][3] == "dtok"


def test_start_omits_days_when_none(monkeypatch):
    calls = []
    monkeypatch.setattr(learn_cli, "fetch_json", _fake(calls, {
        ("POST", "/quests"): {"slug": "a", "status": "queued", "url": "/u"}}))
    learn_cli.main(BASE + ["start", "x", "--no-watch"])
    assert "days" not in calls[0][4]
