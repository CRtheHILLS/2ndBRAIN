"""Quest source collector: search every connector per dot, score, pick by quota,
fetch full text, store as raw markdown in the quest's book, keep a ledger."""
import datetime as dt
import difflib
import hashlib

from . import catalog, index, quest, store
from .config import get_settings
from .connectors import registry, webpage
from .connectors.base import Candidate, normalize_url
from .models import Dot, QuestPlan, SourceLedger, SourceRecord, SpecialSource

KIND_W = {"official": 1.0, "textbook": 0.9, "encyclopedia": 0.9, "paper": 0.9,
          "book": 0.85, "video": 0.6, "web": 0.5, "forum": 0.4}


def score(c: Candidate, lang_wanted: str, prefer_kinds: list[str]) -> float:
    lang_w = 1.0 if (not c.lang or c.lang == lang_wanted) else 0.8
    return KIND_W.get(c.kind, 0.5) * c.authority * lang_w * (1.1 if c.kind in prefer_kinds else 1.0)


def _s(c: Candidate) -> float:
    s = c.extra.get("score")
    return float(s) if s is not None else score(c, "ko", [])


def dedup(cands: list[Candidate]) -> list[Candidate]:
    kept: list[Candidate] = []
    for c in sorted(cands, key=_s, reverse=True):
        key = normalize_url(c.url)
        title = c.title.strip().lower()
        if any(normalize_url(k.url) == key
               or difflib.SequenceMatcher(None, title, k.title.strip().lower()).ratio() >= 0.9
               for k in kept):
            continue
        kept.append(c)
    return kept


def pick_for_dot(cands: list[Candidate], quota: int) -> list[Candidate]:
    ranked = sorted(cands, key=_s, reverse=True)
    picked: list[Candidate] = []

    def videos() -> int:
        return sum(c.kind == "video" for c in picked)

    def take(c: Candidate | None) -> None:
        if c is not None and c not in picked and len(picked) < quota:
            if c.kind != "video" or videos() == 0:
                picked.append(c)

    take(next((c for c in ranked if c.kind == "encyclopedia"), None) or (ranked[0] if ranked else None))
    rest = [c for c in ranked if c not in picked]
    take(next((c for c in rest if c.kind in ("paper", "official")), None)
         or next((c for c in rest if c.kind != "video" or videos() == 0), None))
    for c in ranked:
        take(c)
    if picked and not any(c.lang == "ko" for c in picked):
        weakest = min(picked, key=_s)
        others_video = sum(c.kind == "video" for c in picked if c is not weakest)
        ko = next((c for c in ranked if c.lang == "ko" and c not in picked
                   and (c.kind != "video" or others_video == 0)), None)
        if ko is not None:
            picked[picked.index(weakest)] = ko
    return picked


def _merge_status(ledger: SourceLedger, status: dict[str, str]) -> None:
    for name, st in status.items():
        row = ledger.connector_status.setdefault(name, {"ok": 0, "error": 0, "results": 0})
        if st.startswith("ok"):
            row["ok"] += 1
            try:
                row["results"] += int(st.split(":", 1)[1])
            except (IndexError, ValueError):
                pass
        else:
            row["error"] += 1


def _save_raw(slug: str, day: int, dot: str, url: str, title: str, kind: str, connector: str,
              lang: str, sc: float, text: str) -> tuple[str, int]:
    text = text[:get_settings().quest_max_doc_chars]
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    filename = f"src-d{day:02d}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]}.md"
    path = store.raw_dir(slug) / filename
    meta = {"book": slug, "source": url, "sha256": sha, "kind": kind, "connector": connector,
            "score": round(sc, 3), "day": day, "dot": dot, "lang": lang, "title": title,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds")}
    store.write_md(path, meta, text)
    catalog.register(slug, filename, path, sha)
    return filename, len(text)


def run_dot(slug: str, day: int, dot: Dot, quota: int, ledger: SourceLedger,
            used_urls: set[str]) -> int:
    queries = [(q, "ko") for q in dot.queries_ko[:2]] + [(q, "en") for q in dot.queries_en[:2]]
    if not queries:
        if dot.concept_ko:
            queries.append((dot.concept_ko, "ko"))
        if dot.concept_en:
            queries.append((dot.concept_en, "en"))
    pool: dict[str, Candidate] = {}
    for q, lang in queries:
        found, status = registry.search_all(q, lang)
        _merge_status(ledger, status)
        for c in found:
            c.extra["score"] = score(c, lang, dot.prefer_kinds)
            key = normalize_url(c.url)
            if c.connector == "vault" or c.url.startswith("vault://"):
                if not any(h["url"] == c.url and h["dot"] == dot.concept_ko for h in ledger.vault_hits):
                    ledger.vault_hits.append({"url": c.url, "title": c.title, "dot": dot.concept_ko,
                                              "day": day, "score": round(c.extra["score"], 3)})
                continue
            if key in used_urls or c.url in used_urls:
                continue
            if key not in pool or pool[key].extra["score"] < c.extra["score"]:
                pool[key] = c
    cands = dedup(list(pool.values()))
    first = pick_for_dot(cands, quota)
    order = first + [c for c in cands if c not in first]
    saved = attempts = 0
    for c in order:
        if saved >= quota or attempts >= quota + 2:
            break
        attempts += 1
        sc = c.extra["score"]
        why = f"'{dot.concept_ko}' 점의 {c.kind} 출처 (점수 {sc:.2f}, {c.connector})"
        rec = dict(url=c.url, title=c.title, kind=c.kind, connector=c.connector, score=round(sc, 3),
                   day=day, dot=dot.concept_ko, lang=c.lang, why_picked=why)
        doc = registry.fetch(c)
        if doc is None or not doc.text.strip():
            reason = "본문을 가져오지 못함" if doc is None else "본문이 비어 있음"
            ledger.sources.append(SourceRecord(**rec, fetched=False, reason=reason))
            used_urls.update({c.url, normalize_url(c.url)})  # never retry a dead URL
            continue
        name, chars = _save_raw(slug, day, dot.concept_ko, c.url, doc.title or c.title, c.kind,
                                c.connector, doc.lang or c.lang, sc, doc.text)
        ledger.sources.append(SourceRecord(**rec, fetched=True, raw_file=name, chars=chars))
        used_urls.update({c.url, normalize_url(c.url), doc.url, normalize_url(doc.url)})
        saved += 1
    return saved


def run_special(slug: str, specials: list[SpecialSource], ledger: SourceLedger,
                used_urls: set[str] | None = None, limit: int | None = None) -> int:
    used = used_urls if used_urls is not None else set()
    saved = 0
    for sp in specials:
        row = {"name": sp.name, "url": sp.url, "why": sp.why, "ok": False, "reason": "", "chars": 0}
        if limit is not None and saved >= limit:
            row["reason"] = "수집 예산 소진"
        elif not sp.url:
            row["reason"] = "URL 없음"
        elif sp.url in used or normalize_url(sp.url) in used:
            row["reason"] = "이미 수집한 URL"
        else:
            try:
                doc = webpage.fetch_url(sp.url)
            except Exception:
                doc = None
            if doc is None or not doc.text.strip():
                row["reason"] = "본문을 가져오지 못함"
            else:
                name, chars = _save_raw(slug, 0, "특별 출처", sp.url, doc.title or sp.name, "official",
                                        "webpage", doc.lang, 1.0, doc.text)
                ledger.sources.append(SourceRecord(
                    url=sp.url, title=doc.title or sp.name, kind="official", connector="webpage",
                    score=1.0, day=0, dot="특별 출처", lang=doc.lang,
                    why_picked=f"특별 출처 '{sp.name}': {sp.why}".rstrip(": "),
                    fetched=True, raw_file=name, chars=chars))
                used.update({sp.url, normalize_url(sp.url)})
                row.update(ok=True, chars=chars, raw_file=name)
                saved += 1
        ledger.special_tried.append(row)
    return saved


def collect_quest(slug: str, plan: QuestPlan) -> SourceLedger:
    s = get_settings()
    store.upsert_book(slug, plan.title_ko)
    ledger = SourceLedger()
    used: set[str] = set()
    saved = 0
    reserve = min(3, len(plan.special_sources))
    dots = [(day.n, dot) for day in plan.days for dot in day.dots]
    try:
        for i, (n, dot) in enumerate(dots):
            remaining = s.quest_max_sources - reserve - saved
            if remaining <= 0:
                break
            quota_now = max(1, min(s.quest_quota_per_dot, remaining // (len(dots) - i)))
            try:
                saved += run_dot(slug, n, dot, quota_now, ledger, used)
            finally:
                quest.save_ledger(slug, ledger)
        run_special(slug, plan.special_sources, ledger, used, limit=max(0, s.quest_max_sources - saved))
        ledger.new_connectors_tried = [n for n, row in ledger.connector_status.items() if row["results"] > 0]
        index.rebuild()
    finally:
        quest.save_ledger(slug, ledger)
    return ledger
