import json, re
from . import llm, store

DISTILL_SYSTEM = """You are Clair, CR's knowledge companion. From the raw page transcriptions of ONE book, produce JSON only:
{"summary": "<400-700자 한국어 요약>",
 "concepts": [{"name": "<개념명 (원어 병기)>", "explain": "<2-3문장>", "why_it_matters": "<1문장>"}],  // 8-20개
 "quotes": [{"text": "<==밑줄== 부분 우선, 원문 그대로>", "page": <int or null>}],
 "cr_notes": ["<'## 독자 메모' 에 있던 CR의 메모 그대로>"]}
Keep Korean/English as in the source. No markdown fences."""

def _md_list(items, fmt): return "\n".join(fmt(i) for i in items) + "\n"

def distill_book(slug: str) -> dict:
    text = "\n\n".join(store.read_md(p)[1] for p in sorted(store.raw_dir(slug).glob("*.md")))
    raw = llm.complete(DISTILL_SYSTEM, text, smart=True)
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M)
    d = json.loads(raw)
    n = store.notes_dir(slug); m = {"book": slug}
    store.write_md(n / "summary.md", m, d["summary"])
    store.write_md(n / "concepts.md", m, _md_list(d["concepts"],
        lambda c: f"## {c['name']}\n{c['explain']}\n\n**왜 중요해?** {c['why_it_matters']}\n"))
    store.write_md(n / "quotes.md", m, _md_list(d["quotes"], lambda q: f"> {q['text']} (p.{q.get('page')})\n"))
    store.write_md(n / "cr-notes.md", m, _md_list(d.get("cr_notes", []), lambda s: f"- {s}"))

    book_json = store.book_dir(slug) / "book.json"
    book = json.loads(book_json.read_text("utf-8"))
    book["status"] = "distilled"
    book_json.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")

    return d
