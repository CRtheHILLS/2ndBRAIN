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
