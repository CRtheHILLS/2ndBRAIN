"""Quest stage bodies.  ``quest.run`` drives them through ``STAGE_FUNCS``.

Each stage loads/saves quest.json itself and routes every think call through
``quest.think_or_cached`` so it can park and resume.
"""
import json
import re
import time

from . import catalog, graph, index, levels, models, prompts, quest, render, store, think

_PARTICLES = re.compile(r"(에서|으로|을|를|이|가|은|는|의|에|로|와|과|도)$")
_STOPWORDS = {"배우고", "싶어", "이해하고", "알고", "공부하자", "가르쳐", "줘", "나", "저", "완벽히", "확실히"}


class _ParkedInCatalog(think.ThinkUnavailable):
    """Carries a parked task id through catalog.learn_batch (it re-raises only ThinkUnavailable)."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__([f"과제 대기: {task_id}"])


# --- plan -------------------------------------------------------------------

def _tokens(sentence: str) -> list[str]:
    out = []
    for tok in re.findall(r"\w+", sentence):
        stripped = _PARTICLES.sub("", tok)
        tok = stripped if len(stripped) >= 2 else tok
        if len(tok) >= 2 and tok not in _STOPWORDS and tok not in out:
            out.append(tok)
    return out


def _plan_user(q: dict) -> str:
    sentence = q["sentence"]
    titles, seen = [], set()
    for h in index.search(sentence, 20):
        if h["path"] not in seen:
            seen.add(h["path"])
            titles.append(f"- {h['slug']}: {h['path']}")
    concepts, ids = [], set()
    for tok in _tokens(sentence):
        for n in graph.search_labels(tok, 5):
            if n and n.get("kind") == "concept" and n["id"] not in ids and len(concepts) < 20:
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
    q = quest.load(slug)
    data = quest.think_or_cached(slug, "plan", "plan", prompts.plan_system(q["days_requested"]),
                                 _plan_user(q), models.QuestPlan)
    plan = models.QuestPlan.model_validate(data)
    if not plan.days:
        raise ValueError("계획에 날짜가 하나도 없음")
    if len(plan.days) != q["days_requested"]:
        quest.log(slug, event="plan_days_mismatch", requested=q["days_requested"], got=len(plan.days))
    q = quest.load(slug)
    q["plan"] = plan.model_dump()
    quest.save(slug, q)
    levels.set_level(f"quest:{slug}", q["level"])
    store.upsert_book(slug, plan.title_ko)
    graph.upsert_node(f"quest:{slug}", "quest", plan.title_ko, plan.title_en, summary=plan.one_line_goal)


# --- collect ----------------------------------------------------------------

def stage_collect(slug: str) -> None:
    from . import collect  # collect imports quest
    plan = models.QuestPlan.model_validate(quest.load(slug)["plan"])
    ledger = collect.collect_quest(slug, plan)
    q = quest.load(slug)
    q["budget"]["sources"] = sum(1 for s in ledger.sources if s.fetched)
    quest.save(slug, q)


# --- classify ---------------------------------------------------------------

def _classify_task_id(slug: str, user: str) -> str:
    """Same batch text -> same task (a submitted answer is reused); else max index + 1."""
    nums = []
    for t in quest.all_tasks(slug):
        tid = str(t.get("task_id", ""))
        m = re.fullmatch(r"classify-(\d+)", tid)
        if not m:
            continue
        if t.get("user") == user and t.get("status") != "superseded":
            return tid
        nums.append(int(m.group(1)))
    # files that failed to parse still occupy their numbers
    for p in (quest.quest_dir(slug) / "tasks").glob("classify-*.json"):
        m = re.fullmatch(r"classify-(\d+)", p.stem)
        if m:
            nums.append(int(m.group(1)))
    return f"classify-{max(nums) + 1 if nums else 0}"


def _book_pending(slug: str) -> int:
    return sum(1 for i in catalog.pending() if i.get("book") == slug)


def stage_classify(slug: str) -> None:
    def complete(system: str, user: str) -> str:
        tid = _classify_task_id(slug, user)
        try:
            result = quest.think_or_cached(slug, tid, "classify", system, user, models.CatalogBatch)
        except quest.Parked as p:
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
        raise quest.Parked(e.task_id) from None
    q = quest.load(slug)
    q["summary"]["n_concepts"] = len(graph.node_ids_in_book(slug, kind="concept"))
    q["summary"]["classify_remaining"] = _book_pending(slug)
    quest.save(slug, q)


# --- later tasks --------------------------------------------------------------

def stage_teach(slug: str) -> None:  # Task 12
    pass


def stage_bridge(slug: str) -> None:  # Task 15
    pass


def stage_archive(slug: str) -> None:
    """Index, render, and fill the final summary (helpers below)."""
    _stage_archive(slug)


STAGE_FUNCS = {"plan": stage_plan, "collect": stage_collect, "classify": stage_classify,
               "teach": stage_teach, "bridge": stage_bridge, "archive": stage_archive}


# --- archive helpers (Task 13) ------------------------------------------------

COST_TABLE = {"anthropic": (3, 15), "gemini": (0, 0), "xai": (0.2, 0.5), "text": (0, 0)}  # USD / M tokens (in, out)


def _estimate_cost(slug: str) -> float:
    path = quest.quest_dir(slug) / "log.jsonl"
    total = 0.0
    if path.is_file():
        for line in path.read_text("utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "provider" not in row:
                continue
            pin, pout = COST_TABLE.get(row["provider"], (0, 0))
            total += (row.get("in") or 0) * pin / 1e6 + (row.get("out") or 0) * pout / 1e6
    return round(total, 4)


def _stage_archive(slug: str) -> None:
    t0 = time.monotonic()
    index.rebuild()
    render_quest = getattr(render, "render_quest", None)  # added by the render task
    if render_quest is not None:
        render_quest(slug)
    render.render_shelf()
    q = quest.load(slug)
    ledger = quest.load_ledger(slug)
    s = q["summary"]
    new_sources = list(ledger.new_connectors_tried) + [
        str(r.get("name")) for r in ledger.special_tried if r.get("ok")]
    s.update(
        n_sources=sum(1 for x in ledger.sources if x.fetched),
        n_concepts=len(graph.node_ids_in_book(slug, kind="concept")),
        cost_estimate=_estimate_cost(slug),
        new_sources=new_sources,
        one_line_goal=(q.get("plan") or {}).get("one_line_goal", ""),
        elapsed_seconds=round(q["budget"]["seconds"] + (time.monotonic() - t0), 3),
        bridges=s.get("bridges", 0),
        bridges_top=s.get("bridges_top", []),
        day1_big_idea=s.get("day1_big_idea", ""),
        pages=s.get("pages", {}),
        stage="done",
    )
    quest.save(slug, q)
