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


# --- teach --------------------------------------------------------------------

TEACH_MAX_CHARS = 12_000
_KIND_KO = {"skill": "몸으로 익히는 기술", "topic": "이해하고 싶은 주제", "question": "여러 주장이 엮인 물음"}


def _dot_excerpts(slug: str, dot: dict) -> list[str]:
    from . import retrieve  # local: keeps this file's import line untouched for parallel tasks
    hits = retrieve.excerpts(dot["concept_ko"], slug, k=3)
    if not hits and dot.get("concept_en"):
        hits = retrieve.excerpts(dot["concept_en"], slug, k=3)
    return [f"   [출처: {h['title']}] {' '.join(h['text'].split())}" for h in hits]


def _teach_user(slug: str, q: dict, day: dict, first_n: int, prev: dict | None,
                ledger: models.SourceLedger) -> str:
    """Day message.  Level rules come first so no trim can drop them; when too long, trim
    excerpts, then bridge hints, then yesterday's dot lines, and only then cut the tail."""
    plan, n = q["plan"], day["n"]
    level = q.get("level") or "초등"
    head = [f"수준: {level}", prompts.TEACH_LEVEL_RULES.get(level, prompts.TEACH_LEVEL_RULES["초등"]), "",
            f"퀘스트: {plan['title_ko']} (종류: {_KIND_KO.get(plan['kind'], plan['kind'])})",
            f"목표: {plan['one_line_goal']}",
            f"Day {n}/총 {len(plan['days'])}",
            f"오늘의 큰 생각: {day['big_idea']}"]
    h = plan.get("honesty") or {}
    if n == first_n and any(h.get(k) for k in ("learnable_by_reading", "needs_practice", "hype_warning")):
        head += ["", "정직 상자 (첫날이니 이야기나 점 설명에서 한 번 짚어 주기):"]
        for key, label in (("learnable_by_reading", "읽어서 되는 것"), ("needs_practice", "몸으로 해야 하는 것"),
                           ("hype_warning", "과장 주의")):
            if h.get(key):
                head.append(f"- {label}: {', '.join(h[key])}")
    head += ["", "오늘의 점:"]
    dots = []  # (lines, excerpts) per dot
    for i, d in enumerate(day["dots"], 1):
        en = f" ({d['concept_en']})" if d.get("concept_en") else ""
        urls = list(dict.fromkeys(s.url for s in ledger.sources if s.fetched and s.dot == d["concept_ko"]))
        why = f" — {d['why_one_line']}" if d.get("why_one_line") else ""
        lines = [f"{i}. {d['concept_ko']}{en}{why} — 증거 힌트: {d.get('evidence_grade_hint') or '연구중'}",
                 "   쓸 수 있는 출처 URL: " + (" , ".join(urls) if urls else "(없음 — sources는 빈 배열)"),
                 "   자료 발췌:"]
        dots.append((lines, _dot_excerpts(slug, d)))
    yesterday = [f"- {c['concept_ko']}: {c['one_line']}" for c in prev["dots"]] if prev else []
    bridges = [f"- {b['target']}: {b.get('why') or ''}".rstrip(": ") for b in plan.get("bridge_hints") or []]

    def build() -> str:
        body = [line for lines, exs in dots for line in (*lines, *(exs or ["   (발췌 없음)"]))]
        tail = []
        if prev:
            tail += ["", "어제 배운 것:", f"- 큰 생각: {prev['big_idea_one_line']}", *yesterday]
        if bridges:
            tail += ["", "다른 분야와 이어질 만한 곳:", *bridges]
        return "\n".join(head + body + tail)

    msg = build()
    while len(msg) > TEACH_MAX_CHARS and any(exs for _, exs in dots):
        max(dots, key=lambda d: len(d[1]))[1].pop()
        msg = build()
    if len(msg) > TEACH_MAX_CHARS and bridges:
        bridges.clear()
        msg = build()
    while len(msg) > TEACH_MAX_CHARS and yesterday:
        yesterday.pop()
        msg = build()
    return msg[:TEACH_MAX_CHARS]


def _fill_concept_ids(lesson: dict, day: dict) -> None:
    from . import canon
    en_by_ko = {d["concept_ko"]: d.get("concept_en") or "" for d in day["dots"]}
    for d in lesson["dots"]:
        if d["concept_ko"].strip():
            d["concept_id"] = canon.canon(d["concept_ko"], en_by_ko.get(d["concept_ko"], ""))


def _link_lesson(slug: str, title_ko: str, lesson: dict) -> None:
    lid = f"lesson:{slug}:day-{lesson['n']}"
    graph.upsert_node(lid, "lesson", f"{title_ko} Day {lesson['n']}", summary=lesson["big_idea_one_line"])
    for cid in dict.fromkeys(d["concept_id"] for d in lesson["dots"] if d["concept_id"]):
        graph.add_edge(cid, lid, "taught_in")
    graph.add_edge(lid, f"book:{slug}", "in_book")


def stage_teach(slug: str) -> None:
    from . import render
    q = quest.load(slug)
    plan = q["plan"]
    days = sorted(plan["days"], key=lambda d: d["n"])
    system = prompts.teach_system(q.get("level") or "초등")
    ledger = quest.load_ledger(slug)
    site = f"/site/quests/{slug}"
    prev, day_pages, day1 = None, [], ""
    for day in days:
        n = day["n"]
        lesson = render.load_day(slug, n)
        if lesson is None:
            user = _teach_user(slug, q, day, days[0]["n"], prev, ledger)
            data = quest.think_or_cached(slug, f"teach-day-{n}", "teach", system, user, models.DayLesson,
                                         context={"day": n})
            lesson = models.DayLesson.model_validate(data).model_dump()
            lesson["n"] = n
            _fill_concept_ids(lesson, day)
            _link_lesson(slug, plan["title_ko"], lesson)
            p = quest.quest_dir(slug) / "days" / f"day-{n}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(lesson, ensure_ascii=False, indent=2), "utf-8")
            render.render_quest_day(slug, n)
            quest.log(slug, event="teach_day", day=n, dots=len(lesson["dots"]))
        elif not (store.site_dir() / "quests" / slug / f"day-{n}.html").exists():
            render.render_quest_day(slug, n)
        day_pages.append(f"{site}/day-{n}.html")
        day1 = day1 or lesson["big_idea_one_line"]
        prev = lesson
    render.render_quest(slug)
    q = quest.load(slug)  # think_or_cached saved the budget meanwhile
    q["summary"]["pages"] = {"index": f"{site}/index.html", "days": day_pages}
    q["summary"]["day1_big_idea"] = day1
    quest.save(slug, q)


# --- later tasks --------------------------------------------------------------


def stage_bridge(slug: str) -> None:
    """Link this quest's concepts to concepts learned in other books/quests (honest links only)."""
    from . import bridge, render
    days = [d["n"] for d in quest.load(slug)["plan"]["days"]]
    lessons = {n: render.load_day(slug, n) for n in days}
    taught = [d["concept_id"] for les in lessons.values() if les for d in les["dots"] if d["concept_id"]]
    node_ids = list(dict.fromkeys(graph.node_ids_in_book(slug, kind="concept") + taught))
    made = bridge.rebridge(node_ids, slug=slug, task_id="bridge")
    shown = bridge.bridges_for(node_ids)
    q = quest.load(slug)  # think_or_cached saved the budget meanwhile
    q["summary"]["bridges"] = len(shown)
    q["summary"]["bridges_top"] = [{"a": b["src_label"], "b": b["dst_label"], "reason": b["reason"]}
                                   for b in shown[:3]]
    quest.save(slug, q)
    quest.log(slug, event="bridge", made=len(made), shown=len(shown))
    bridged = {graph.resolve(b["src"]) for b in shown}
    for n, les in lessons.items():
        if les and bridged & {graph.resolve(d["concept_id"]) for d in les["dots"] if d["concept_id"]}:
            render.render_quest_day(slug, n)
    render.render_quest(slug)
    if made:  # older quests that teach the other ends get their pages refreshed too
        others = [s for s in bridge.affected_quests([b["dst"] for b in made]) if s != slug]
        if others:
            bridge.rerender_affected([b["dst"] for b in made])


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
