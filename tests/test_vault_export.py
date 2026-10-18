import io
import zipfile

from fastapi.testclient import TestClient

from brain import graph, vault_export
from tests.test_render_quest import make_quest

H = {"X-Brain-Token": "test-token"}


def _zip():
    z = zipfile.ZipFile(io.BytesIO(vault_export.build_zip()))
    return z, {n: z.read(n).decode("utf-8") for n in z.namelist()}


def test_vault_zip_has_concept_quest_source_files_and_wikilinks(data_dir):
    graph.upsert_node("lift", "concept", "양력", "lift", field_code="A1", summary="위로 뜨는 힘")
    graph.upsert_node("wing", "concept", "날개", "wing", field_code="A1")
    graph.add_edge("lift", "wing", "bridge", reason="날개가 만든다")
    graph.upsert_node("src:abc123", "source", "항공 입문", summary="요약")
    graph.add_edge("src:abc123", "lift", "about")
    graph.upsert_node("book:bk", "book", "bk")
    graph.add_edge("src:abc123", "book:bk", "in_book")
    make_quest("heli", days=(1,))
    _, f = _zip()
    names = list(f)
    c = next(n for n in names if n.endswith("/양력.md"))
    assert c.startswith("vault/") and c.count("/") == 3
    assert "[[날개]]" in f[c] and "bridge" in f[c] and "[[퀘스트/heli/day-1]]" in f[c]
    assert "# 양력 (lift)" in f[c] and "[[src-abc123]]" in f[c]
    day = f["vault/퀘스트/heli/day-1.md"]
    assert "[[양력]]" in day and "https://ex.org/lift" in day and "Q. 왜 뜰까?" in day
    assert "vault/퀘스트/heli/README.md" in names
    assert "Obsidian" in f["vault/README.md"]
    assert "vault/자료/src-abc123.md" in names and "[[양력]]" in f["vault/자료/src-abc123.md"]
    assert "vault/서재/bk.md" in names and "[[src-abc123]]" in f["vault/서재/bk.md"]


def test_vault_filename_collision_suffix(data_dir):
    graph.upsert_node("c:1", "concept", "소리/파동?", field_code="A1")
    graph.upsert_node("c:2", "concept", "소리/파동?", field_code="A1")
    graph.upsert_node("c:3", "concept", "무소속", field_code="")
    _, f = _zip()
    stems = sorted(n.rsplit("/", 1)[1] for n in f if "소리" in n)
    assert stems == ["소리 파동-A1.md", "소리 파동.md"]
    assert "vault/미분류/무소속.md" in f


def test_vault_route_requires_token_and_returns_zip(data_dir):
    from api.main import app
    with TestClient(app) as c:
        assert c.get("/vault.zip").status_code == 401
        r = c.get("/vault.zip", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/zip")
    assert "2ndbrain-vault.zip" in r.headers["content-disposition"]
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist()


def test_vault_stems_global_unique_and_links_resolve(data_dir):
    graph.upsert_node("c:1", "concept", "파동", field_code="A1")
    graph.upsert_node("c:2", "concept", "파동", field_code="B1")
    graph.upsert_node("c:3", "concept", "CON", field_code="A1")
    graph.add_edge("c:1", "c:2", "bridge", reason="같은 이름")
    _, f = _zip()
    names = [n.rsplit("/", 1)[1][:-3] for n in f if n.count("/") == 3]
    assert len(names) == len(set(n.lower() for n in names)) and "CON_" in names
    c1 = next(v for v in f.values() if 'id: "c:1"' in v)
    c2 = next(v for v in f.values() if 'id: "c:2"' in v)
    s2 = [n for n in names if n.startswith("파동") and n != "파동"]
    assert len(s2) == 1 and f"[[{s2[0]}]]" in c1 and "[[파동]]" in c2


def test_vault_source_url_from_raw_frontmatter(data_dir):
    from brain import catalog, store
    raw = data_dir / "books" / "bk" / "raw" / "a.md"
    store.write_md(raw, {"source": "https://ex.org/a"}, "본문")
    eid = catalog.make_id("bk", "a.md")
    ep = catalog.entry_path(eid)
    ep.parent.mkdir(parents=True, exist_ok=True)
    ep.write_text('{"id": "%s", "book": "bk", "file": "a.md", "path": "%s", "title": "t"}'
                  % (eid, str(raw).replace("\\", "/")), "utf-8")
    graph.upsert_node("c:1", "concept", "개념", field_code="A1")
    graph.upsert_node("src:" + eid[:16], "source", "문서")
    graph.add_edge("src:" + eid[:16], "c:1", "about")
    _, f = _zip()
    assert "https://ex.org/a" in f["vault/자료/src-" + eid[:16] + ".md"]
    assert "https://ex.org/a" in next(v for k, v in f.items() if k.endswith("/개념.md"))


def test_vault_book_with_lesson_member_exports(data_dir):
    graph.upsert_node("lift", "concept", "양력", "lift", field_code="A1")
    graph.upsert_node("rotor", "concept", "회전날개", field_code="A1")
    graph.upsert_node("src:abc123", "source", "항공 입문")
    graph.add_edge("src:abc123", "lift", "about")
    graph.upsert_node("book:heli", "book", "heli")
    graph.add_edge("src:abc123", "book:heli", "in_book")
    graph.upsert_node("lesson:heli:day-1", "lesson", "헬리 Day 1")
    graph.add_edge("rotor", "lesson:heli:day-1", "taught_in")
    graph.add_edge("lesson:heli:day-1", "book:heli", "in_book")
    _, f = _zip()
    b = f["vault/서재/heli.md"]
    assert "[[퀘스트/heli/day-1]]" in b and "[[src-abc123]]" in b
    assert "[[회전날개]]" in b and "[[양력]]" in b
    assert "lesson" not in b.split("## 수업")[0]  # lessons are not listed as sources


def test_vault_stem_strips_obsidian_link_breakers(data_dir):
    graph.upsert_node("c:arr", "concept", "[배열]#1^a|b", field_code="")
    _, f = _zip()
    name = next(n for n in f if 'id: "c:arr"' in f[n])
    stem = name.rsplit("/", 1)[1][:-3]
    assert not any(ch in stem for ch in "[]#^|") and "배열" in stem
