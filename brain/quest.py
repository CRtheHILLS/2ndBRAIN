"""Quest state files and the resumable stage runner.

Layout under ``DATA_DIR/quests/<slug>``: ``quest.json``, ``log.jsonl``,
``sources.json`` and ``tasks/<task_id>.json``.  Every think call of the runner
goes through a task file with a deterministic id (``plan``, ``classify-<n>``,
``teach-day-<n>``, ``bridge``), so an API model or CR's own Claude session can
fill the same JSON task and the runner resumes where it parked.
"""
import datetime as dt
import json
import os
import re
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import catalog, graph, index, levels, models, prompts, store, think
from .config import get_settings
from .slug import slugify

_ENDINGS = re.compile(
    r"\s*(을|를)?\s*(배우고\s*싶(어|어요|다)|이해하고\s*싶(어|어요|다)|알고\s*싶(어|어요|다)|"
    r"공부하자|공부하고\s*싶(어|어요|다)|가르쳐\s*줘(요)?|가르쳐\s*주세요|알려\s*줘(요)?)\s*$")
_LEAD = re.compile(r"^\s*(나|저)\s+")


def quests_root() -> Path:
    p = get_settings().data_dir / "quests"
    p.mkdir(parents=True, exist_ok=True)
    return p


def quest_dir(slug: str) -> Path:
    return quests_root() / slug


def normalize_sentence(s: str) -> str:
    t = s.lower()
    t = re.sub(r"[^\w\s]|_", " ", t)  # punctuation and emoji
    t = re.sub(r"\s+", " ", t).strip()
    t = _LEAD.sub("", t)
    t = _ENDINGS.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def slug_for(sentence: str) -> str:
    body = slugify(normalize_sentence(sentence) or sentence)[:40].strip("-")
    return f"quest-{dt.date.today():%Y%m%d}-{body}".rstrip("-")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def load(slug: str) -> dict:
    return json.loads((quest_dir(slug) / "quest.json").read_text("utf-8"))


def save(slug: str, q: dict) -> None:
    q["updated_at"] = _now()
    d = quest_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "quest.json.tmp"
    tmp.write_text(json.dumps(q, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, d / "quest.json")


def list_quests() -> list[dict]:
    out = []
    for p in quests_root().glob("*/quest.json"):
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(out, key=lambda q: (q.get("created_at", ""), q.get("slug", "")), reverse=True)


def find_existing(sentence: str) -> str | None:
    key = normalize_sentence(sentence)
    if not key:
        return None
    for q in list_quests():  # newest first
        if normalize_sentence(q.get("sentence", "")) == key:
            return q["slug"]
    return None


def _extract_days(sentence: str) -> int:
    if re.search(r"하루(?!키)|오늘 안에|하룻밤", sentence):
        return 1
    t = re.sub(r"\d{1,2}\s*월\s*\d{1,2}\s*일", " ", sentence)  # calendar dates are not durations
    m = re.search(r"(?<!\d)(\d{1,2})\s*일(?![반본월])", t)
    if m and 1 <= int(m.group(1)) <= 30:
        return int(m.group(1))
    return 7


def _extract_level(sentence: str) -> str:
    if re.search(r"전문가|전문적으로|전문\s*수준", sentence):
        return "전문"
    if re.search(r"일반인|교양|일반\s*수준", sentence):
        return "일반"
    return "초등"


def create(sentence: str, days: int | None = None, level: str | None = None,
           started_by: str = "cli") -> dict:
    existing = find_existing(sentence)
    if existing:
        q = load(existing)
        q["existing"] = True
        return q
    slug = slug_for(sentence)
    base, n = slug, 2
    while quest_dir(slug).exists():
        slug = f"{base}-{n}"
        n += 1
    now = _now()
    q = {
        "slug": slug, "sentence": sentence,
        "days_requested": days if days is not None else _extract_days(sentence),
        "level": level or _extract_level(sentence),
        "status": "queued", "stage_done": [], "plan": None,
        "created_at": now, "updated_at": now, "started_by": started_by,
        "error": None, "summary": {},
        "budget": {"think_calls": 0, "sources": 0, "seconds": 0.0},
    }
    save(slug, q)
    q["existing"] = False
    return q


def log(slug: str, **fields) -> None:
    d = quest_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": _now(), **fields}, ensure_ascii=False) + "\n")


def save_ledger(slug: str, ledger: models.SourceLedger) -> None:
    d = quest_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "sources.json").write_text(ledger.model_dump_json(indent=2), "utf-8")


def load_ledger(slug: str) -> models.SourceLedger:
    p = quest_dir(slug) / "sources.json"
    if not p.is_file():
        return models.SourceLedger()
    return models.SourceLedger.model_validate_json(p.read_text("utf-8"))


# ---------------------------------------------------------------------------
# runner: stages + thinker-agnostic task protocol
# ---------------------------------------------------------------------------

STAGES = ("plan", "collect", "classify", "teach", "bridge", "archive")
TASK_KEYS = ("task_id", "kind", "schema", "system", "user", "context", "created_at", "error")


class Parked(Exception):
    """A think task is open; the quest waits for a thinker (API model or a human session)."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(task_id)


class _ParkedInCatalog(think.ThinkUnavailable):
    """Carries a parked task id through catalog.learn_batch (it re-raises only ThinkUnavailable)."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__([f"과제 대기: {task_id}"])


def task_path(slug: str, task_id: str) -> Path:
    return quest_dir(slug) / "tasks" / f"{task_id}.json"


def _read_task(slug: str, task_id: str) -> dict | None:
    p = task_path(slug, task_id)
    if not p.is_file():
        return None
    return json.loads(p.read_text("utf-8"))


def _write_task(slug: str, task: dict) -> None:
    p = task_path(slug, task["task_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, p)


def _all_tasks(slug: str) -> list[dict]:
    d = quest_dir(slug) / "tasks"
    out = []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def open_tasks(slug: str) -> list[dict]:
    tasks = [{k: t.get(k) for k in TASK_KEYS} for t in _all_tasks(slug) if t.get("status") == "open"]
    return sorted(tasks, key=lambda t: t["created_at"] or "")


def task_result(slug: str, task_id: str) -> dict | None:
    t = _read_task(slug, task_id)
    return t["result"] if t and t.get("status") == "done" else None


def _park(slug: str, task: dict, reason: str):
    task.update(status="open", error=reason)
    _write_task(slug, task)
    log(slug, event="parked", task=task["task_id"], reason=reason)
    raise Parked(task["task_id"])


def think_or_cached(slug: str, task_id: str, kind: str, system: str, user: str,
                    schema: type[BaseModel], context: dict | None = None) -> dict:
    task = _read_task(slug, task_id)
    if task and task.get("status") == "done":
        return task["result"]
    task = task or {"task_id": task_id, "created_at": _now()}
    task.update(kind=kind, schema=schema.__name__, system=system, user=user, context=context)
    if load(slug)["budget"]["think_calls"] >= get_settings().quest_max_think_calls:
        _park(slug, task, "생각 호출 예산 초과")
    try:
        r = think.think(kind, system, user, schema, log_path=quest_dir(slug) / "log.jsonl")
    except think.ThinkUnavailable as e:
        _park(slug, task, "; ".join(e.reasons) or "쓸 수 있는 생각 엔진 없음")
    task.update(status="done", result=r.data, provider=r.provider, model=r.model, error=None)
    _write_task(slug, task)
    q = load(slug)
    q["budget"]["think_calls"] += 1
    save(slug, q)
    return r.data


def submit_task(slug: str, task_id: str, output: dict) -> dict:
    task = _read_task(slug, task_id)
    if task is None:
        raise KeyError(f"과제를 찾을 수 없음: {task_id}")
    schema = models.SCHEMAS[task["schema"]]
    try:
        validated = schema.model_validate(output)
    except ValidationError as e:
        msgs = [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:3]]
        task["error"] = "제출한 결과가 형식에 맞지 않음 — " + " / ".join(msgs)
        _write_task(slug, task)
        raise ValueError(task["error"]) from None
    task.update(status="done", result=validated.model_dump(), error=None, provider="submitted")
    _write_task(slug, task)
    log(slug, event="task_submitted", task=task_id)
    return {"accepted": True, "task_id": task_id}


# --- stages -----------------------------------------------------------------

def _plan_user(q: dict) -> str:
    sentence = q["sentence"]
    titles, seen = [], set()
    for h in index.search(sentence, 20):
        if h["path"] not in seen:
            seen.add(h["path"])
            titles.append(f"- {h['slug']}: {h['path']}")
    concepts, ids = [], set()
    for tok in re.findall(r"\w{2,}", sentence):
        for n in graph.search_labels(tok, 5):
            if n and n["id"] not in ids and len(concepts) < 20:
                ids.add(n["id"])
                en = f" ({n['label_en']})" if n.get("label_en") else ""
                concepts.append(f"- {n['label_ko']}{en}")
    return "\n".join([
        f"배우고 싶은 것: {sentence}",
        f"요청 일수: {q['days_requested']}",
        f"수준: {q['level']}",
        "볼륨에 이미 있는 관련 자료:", *(titles[:20] or ["- (없음)"]),
        "그래프에 이미 있는 관련 개념:", *(concepts or ["- (없음)"]),
    ])


def stage_plan(slug: str) -> None:
    q = load(slug)
    data = think_or_cached(slug, "plan", "plan", prompts.plan_system(q["days_requested"]),
                           _plan_user(q), models.QuestPlan)
    plan = models.QuestPlan.model_validate(data)
    if not plan.days:
        raise ValueError("계획에 날짜가 하나도 없음")
    if len(plan.days) != q["days_requested"]:
        log(slug, event="plan_days_mismatch", requested=q["days_requested"], got=len(plan.days))
    q = load(slug)
    q["plan"] = plan.model_dump()
    save(slug, q)
    levels.set_level(f"quest:{slug}", q["level"])
    store.upsert_book(slug, plan.title_ko)
    graph.upsert_node(f"quest:{slug}", "quest", plan.title_ko, plan.title_en, summary=plan.one_line_goal)


def stage_collect(slug: str) -> None:
    from . import collect  # collect imports quest
    plan = models.QuestPlan.model_validate(load(slug)["plan"])
    ledger = collect.collect_quest(slug, plan)
    q = load(slug)
    q["budget"]["sources"] = sum(1 for s in ledger.sources if s.fetched)
    save(slug, q)


def _classify_task_id(slug: str, user: str) -> str:
    """Same batch text -> same task (a submitted answer is reused); else the next index."""
    known = [t for t in _all_tasks(slug) if str(t.get("task_id", "")).startswith("classify-")]
    for t in known:
        if t.get("user") == user:
            return t["task_id"]
    return f"classify-{len(known)}"


def stage_classify(slug: str) -> None:
    def complete(system: str, user: str) -> str:
        tid = _classify_task_id(slug, user)
        try:
            result = think_or_cached(slug, tid, "classify", system, user, models.CatalogBatch)
        except Parked as p:
            raise _ParkedInCatalog(p.task_id) from None
        return json.dumps(result, ensure_ascii=False)

    stalls = 0
    try:
        for _ in range(3):
            r = catalog.learn_pending(limit=200, llm_complete=complete, book=slug, batch_size=5)
            if r["remaining"] == 0:
                break
            stalls = stalls + 1 if r["learned"] == 0 else 0
            if stalls >= 2:
                break
    except _ParkedInCatalog as e:
        raise Parked(e.task_id) from None
    q = load(slug)
    q["summary"]["n_concepts"] = len(graph.node_ids_in_book(slug, kind="concept"))
    save(slug, q)


def stage_teach(slug: str) -> None:  # Task 12
    pass


def stage_bridge(slug: str) -> None:  # Task 15
    pass


def stage_archive(slug: str) -> None:  # Task 13
    pass


STAGE_FUNCS = {"plan": stage_plan, "collect": stage_collect, "classify": stage_classify,
               "teach": stage_teach, "bridge": stage_bridge, "archive": stage_archive}


def _summarize(slug: str) -> dict:
    return {
        "pages": {},
        "n_sources": sum(1 for s in load_ledger(slug).sources if s.fetched),
        "n_concepts": len(graph.node_ids_in_book(slug, kind="concept")),
        "bridges": 0,
        "cost_estimate": 0.0,
    }


def _finish(slug: str, status: str, error: str | None = None, summary: dict | None = None) -> dict:
    q = load(slug)
    q["status"] = status
    if error is not None:
        q["error"] = error
    q["summary"].update(summary or {})
    save(slug, q)
    return q


def run(slug: str) -> dict:
    """Run every unfinished stage; never raises.  Stages load/save quest.json themselves."""
    q = load(slug)
    q.update(status="running", error=None)
    q["summary"].pop("waiting_task", None)
    save(slug, q)
    limit = get_settings().quest_max_minutes * 60
    try:
        for stage in STAGES:
            q = load(slug)
            if stage in q["stage_done"]:
                continue
            if q["budget"]["seconds"] > limit:
                if "teach" not in q["stage_done"]:
                    log(slug, event="failed", stage=stage, error="실행 시간 예산 초과")
                    return _finish(slug, "failed", error="실행 시간 예산 초과")
                log(slug, event="budget_exceeded", stage=stage)
                q["summary"]["budget_exceeded"] = True
                save(slug, q)
                break
            q["summary"]["stage"] = stage
            save(slug, q)
            t0 = time.monotonic()
            STAGE_FUNCS[stage](slug)
            elapsed = time.monotonic() - t0
            q = load(slug)
            q["stage_done"].append(stage)
            q["budget"]["seconds"] = round(q["budget"]["seconds"] + elapsed, 3)
            q["summary"]["stage"] = next((s for s in STAGES if s not in q["stage_done"]), "done")
            save(slug, q)
            log(slug, event="stage_done", stage=stage, seconds=round(elapsed, 3))
    except Parked as p:
        log(slug, event="waiting_thinker", task=p.task_id)
        return _finish(slug, "waiting_thinker", summary={"waiting_task": p.task_id})
    except Exception as e:  # noqa: BLE001 - run() reports, never raises
        err = f"{type(e).__name__}: {e}"
        log(slug, event="failed", error=err)
        return _finish(slug, "failed", error=err)
    return _finish(slug, "done", summary={**_summarize(slug), "stage": "done"})
