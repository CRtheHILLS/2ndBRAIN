"""Task 15: dot-to-dot bridges between concepts learned in different books/quests."""
import hashlib
import json

import pytest

from brain import bridge, graph, quest, render, think

REASON = "자이로스코프가 쓰러지지 않는 건 각운동량이 지켜지기 때문이에요."


def _seed(book, pairs, code="B2", n=0):
    """One learned catalog entry in ``book`` about the (ko, en) concept pairs."""
    eid = hashlib.sha1(f"{book}-{n}".encode()).hexdigest()
    return graph.ingest_card({"id": eid, "book": book, "title": f"{book} 자료 {n}",
                              "field_code": code,
                              "concept_pairs": [{"ko": ko, "en": en} for ko, en in pairs]})


def _world():
    _seed("양자역학", [("각운동량", "Angular momentum"), ("스핀", "Spin"), ("토크", "Torque")])
    _seed("헬리콥터", [("자이로스코프", "Gyroscope"), ("로터", "Rotor")])


def _fake_complete(answer, seen=None):
    def complete(system, user):
        if seen is not None:
            seen.append((system, user))
        return json.dumps(answer, ensure_ascii=False)
    return complete


def test_candidates_only_from_other_books(data_dir):
    _world()
    _seed("물리 사전", [("자이로스코프 효과", "Gyroscope effect")], code="F3")
    _seed("요리", [("간장", "Soy sauce")], code="P1")
    cands = bridge.candidates("gyroscope")
    ids = [c["id"] for c in cands]
    assert "rotor" not in ids and "gyroscope" not in ids  # same book / self
    assert "soy-sauce" not in ids  # unrelated: no shared field, label or neighbor
    assert {"angular-momentum", "spin", "torque", "gyroscope-effect"} <= set(ids)
    by_id = {c["id"]: c for c in cands}
    assert by_id["angular-momentum"]["why"] == "same_field"
    assert by_id["angular-momentum"]["books"] == ["양자역학"]
    assert by_id["gyroscope-effect"]["why"] == "alias"
    assert ids[0] == "gyroscope-effect"  # alias first
    assert set(by_id["spin"]) == {"id", "label_ko", "label_en", "field_code", "why", "books"}


def test_candidates_wikidata_parent_and_cooccur(data_dir, monkeypatch):
    _world()
    graph.upsert_node("gyroscope", "concept", "자이로스코프", wikidata="Q1")
    _seed("기계", [("팽이", "Spinning top")], code="F4")
    graph.upsert_node("spinning-top", "concept", "팽이", wikidata="Q2")
    calls = []

    def parents(qid):
        calls.append(qid)
        return {"Q1": ["Q99"], "Q2": ["Q99"]}.get(qid, [])
    from brain.connectors import wikidata
    monkeypatch.setattr(wikidata, "parents", parents)
    # cooccur: rotor (same book) co-occurs with blade in another book
    _seed("항공", [("로터", "Rotor"), ("블레이드", "Blade")], n=1)
    by_id = {c["id"]: c for c in bridge.candidates("gyroscope", limit=20)}
    assert by_id["spinning-top"]["why"] == "wikidata_parent"
    assert by_id["blade"]["why"] == "cooccur"
    assert calls.count("Q1") == 1  # cached per call


def test_candidates_dedupe_and_round_robin_cap(data_dir, monkeypatch):
    _seed("헬리콥터", [("자이로스코프", "Gyroscope")])
    _seed("양자역학", [(f"개념{i}", f"Concept {i}") for i in range(12)])
    _seed("물리 사전", [("자이로스코프 축", "Gyroscope axis")], n=1)  # alias AND same field
    cands = bridge.candidates("gyroscope")
    assert len(cands) == 8
    ids = [c["id"] for c in cands]
    assert len(ids) == len(set(ids))
    assert ids[0] == "gyroscope-axis" and cands[0]["why"] == "alias"

    fake = {n: [{"id": f"{n}-{i}", "label_ko": f"{n}{i}", "label_en": "", "field_code": "",
                 "why": "same_field", "books": ["x"]} for i in range(8)] for n in ("a", "b")}
    monkeypatch.setattr(bridge, "candidates", lambda nid, limit=8: fake[nid])
    pairs = bridge.gather_pairs(["a", "b"], max_pairs=6)
    assert len(pairs) == 6
    assert sum(1 for s, _ in pairs if s == "a") == 3 == sum(1 for s, _ in pairs if s == "b")


def test_rebridge_adds_only_confirmed_edges(data_dir):
    _world()
    seen = []
    answer = {"verdicts": [
        {"src": "gyroscope", "dst": "angular-momentum", "connects": True, "rel": "bridge",
         "reason": REASON},
        {"src": "gyroscope", "dst": "spin", "connects": False, "rel": "bridge", "reason": ""},
        {"src": "gyroscope", "dst": "torque", "connects": False, "rel": "related", "reason": ""},
        {"src": "gyroscope", "dst": "rotor", "connects": True, "rel": "bridge", "reason": "x"},
        {"src": "gyroscope", "dst": "gyroscope", "connects": True, "rel": "bridge", "reason": "x"},
    ]}
    made = bridge.rebridge(["gyroscope"], complete=_fake_complete(answer, seen))
    assert made == [{"src": "gyroscope", "dst": "angular-momentum", "rel": "bridge", "reason": REASON}]
    system, user = seen[0]
    assert "억지" in system and "각운동량" in user and "자이로스코프" in user
    edges = graph.neighbors("gyroscope", rels=["bridge"])["edges"]
    assert len(edges) == 1
    assert edges[0]["dst"] == "angular-momentum" and edges[0]["reason"] == REASON
    assert edges[0]["evidence"] == "bridge"


def test_rebridge_no_candidates_skips_think(data_dir, monkeypatch):
    _seed("헬리콥터", [("자이로스코프", "Gyroscope"), ("로터", "Rotor")])

    def boom(*a, **k):
        raise AssertionError("must not think")
    monkeypatch.setattr(think, "think", boom)
    assert bridge.rebridge(["gyroscope", "rotor"], complete=boom) == []
    assert bridge.rebridge([]) == []


def test_rebridge_outside_quest_swallows_think_unavailable(data_dir, monkeypatch):
    _world()

    def unavailable(*a, **k):
        raise think.ThinkUnavailable(["anthropic: no key"])
    monkeypatch.setattr(think, "think", unavailable)
    assert bridge.rebridge(["gyroscope"]) == []
    assert graph.neighbors("gyroscope", rels=["bridge"])["edges"] == []
    with pytest.raises(think.ThinkUnavailable):
        bridge.rebridge(["gyroscope"], strict=True)


def test_bridges_for_labels_and_books(data_dir):
    _world()
    quest.save("quest-heli", {"slug": "quest-heli", "plan": {"title_ko": "헬리콥터 퀘스트"}})
    _seed("quest-heli", [("블레이드", "Blade")], code="F5")
    graph.add_edge("gyroscope", "angular-momentum", "bridge", reason=REASON, evidence="bridge")
    graph.add_edge("gyroscope", "rotor", "bridge", reason="같은 책")  # same book: not shown
    graph.add_edge("gyroscope", "spin", "related", reason="느슨")  # not a shown rel
    graph.add_edge("blade", "torque", "requires", reason="토크를 알아야 해요")
    out = bridge.bridges_for(["gyroscope"])
    assert out == [{"src": "gyroscope", "dst": "angular-momentum", "rel": "bridge", "reason": REASON,
                    "src_label": "자이로스코프", "dst_label": "각운동량", "dst_books": ["양자역학"]}]
    back = bridge.bridges_for(["angular-momentum", "torque"])
    assert [b["rel"] for b in back] == ["bridge", "requires"]  # bridge first
    assert back[0]["src"] == "angular-momentum" and back[0]["dst_books"] == ["헬리콥터"]
    assert back[1]["dst_label"] == "블레이드" and back[1]["dst_books"] == ["헬리콥터 퀘스트"]


def test_affected_quests_and_rerender(data_dir, monkeypatch):
    _world()
    graph.upsert_node("lesson:quest-heli:day-2", "lesson", "헬리콥터 Day 2")
    graph.add_edge("gyroscope", "lesson:quest-heli:day-2", "taught_in")
    graph.add_edge("lesson:quest-heli:day-2", "book:quest-heli", "in_book")
    assert bridge.affected_quests(["gyroscope", "angular-momentum"]) == ["quest-heli"]
    calls = []
    monkeypatch.setattr(render, "render_quest_day", lambda s, n: calls.append(("day", s, n)))

    def index(s):
        calls.append(("index", s))
        raise RuntimeError("렌더 실패")  # swallowed per page
    monkeypatch.setattr(render, "render_quest", index)
    assert bridge.rerender_affected(["gyroscope"]) == ["quest-heli"]
    assert calls == [("day", "quest-heli", 2), ("index", "quest-heli")]
