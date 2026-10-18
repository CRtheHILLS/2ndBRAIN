import httpx
import respx

from brain import canon, graph
from brain.connectors import wikidata


def hit(qid, label="x", aliases=()):
    return lambda lab, lang: {"id": qid, "label": label, "description": "", "aliases": list(aliases)}


def test_split_bilingual():
    assert canon.split_bilingual("양자 얽힘 (Quantum Entanglement)") == ("양자 얽힘", "Quantum Entanglement")
    assert canon.split_bilingual("양자 얽힘 （Quantum Entanglement）") == ("양자 얽힘", "Quantum Entanglement")
    assert canon.split_bilingual("블랙홀 [Black Hole]") == ("블랙홀", "Black Hole")
    assert canon.split_bilingual("블랙홀") == ("블랙홀", "")
    assert canon.split_bilingual("함수 (정의역)") == ("함수 (정의역)", "")


def test_norm():
    assert canon.norm("  Quantum   ENTANGLEMENT ") == "quantum entanglement"


def test_concept_id_prefers_english():
    assert canon.concept_id("Quantum Entanglement", "양자 얽힘") == "quantum-entanglement"
    assert canon.concept_id("", "양자 얽힘") == "양자-얽힘"
    assert canon.concept_id("Spin", "스핀", suffix="N3") == "spin-n3"


def test_canon_reuses_existing_by_alias(data_dir):
    a = canon.canon("양자 얽힘", "Quantum Entanglement", "B4")
    graph.add_alias("얽힘", a)
    assert canon.canon("얽힘") == a
    assert canon.canon("양자 얽힘 (Quantum Entanglement)") == a
    assert canon.canon("quantum entanglement") == a


def test_canon_attaches_qid_from_lookup(data_dir):
    cid = canon.canon("양자 얽힘", "Quantum Entanglement", "B4", lookup=hit("Q215675"))
    assert graph.get_node(cid)["wikidata"] == "Q215675"
    assert graph.find_alias("wd:Q215675") == cid


def test_canon_qid_merges_different_spelling(data_dir):
    a = canon.canon("양자 얽힘", "Quantum Entanglement", "B4", lookup=hit("Q215675"))
    b = canon.canon("얽힘 현상", "", "B4", lookup=hit("Q215675"))
    assert a == b
    assert graph.find_alias("얽힘 현상") == a


def test_canon_disambiguates_same_slug_different_area(data_dir):
    assert canon.canon("스핀", "Spin", "B4", lookup=hit("Q1")) == "spin"
    assert canon.canon("스핀", "Spin", "N3", lookup=hit("Q2")) == "spin-n3"
    assert canon.canon("스핀", "Spin", "B4") == "spin"


def test_canon_survives_lookup_exception(data_dir):
    def boom(label, lang):
        raise RuntimeError("net down")
    cid = canon.canon("블랙홀", "Black Hole", "B4", lookup=boom)
    assert cid == "black-hole" and graph.get_node(cid)["wikidata"] == ""


def test_ingest_card_uses_canon(data_dir):
    entry = {"id": "a" * 32, "title": "t", "field_code": "B4",
             "concept_pairs": [{"ko": "양자 얽힘 (Quantum Entanglement)", "en": ""}]}
    assert graph.ingest_card(entry) == ["quantum-entanglement"]


SEARCH = {"search": [{"id": "Q9", "label": "Other", "description": "d", "aliases": []},
                     {"id": "Q215675", "label": "Quantum entanglement", "description": "phenomenon",
                      "match": {"text": "x"}}]}


@respx.mock
def test_wikidata_search_entity_parses():
    route = respx.get("https://www.wikidata.org/w/api.php").mock(
        return_value=httpx.Response(200, json=SEARCH))
    r = wikidata.search_entity("quantum  Entanglement", "en")
    assert r["id"] == "Q215675" and r["description"] == "phenomenon"
    assert route.calls[0].request.url.params["language"] == "en"
    assert wikidata.search_entity("nothing", "en") is None


@respx.mock
def test_wikidata_search_entity_error_is_none():
    respx.get("https://www.wikidata.org/w/api.php").mock(return_value=httpx.Response(500))
    assert wikidata.search_entity("x", "en") is None


@respx.mock
def test_wikidata_parents():
    respx.get("https://www.wikidata.org/w/api.php").mock(return_value=httpx.Response(200, json={
        "claims": {"P279": [{"mainsnak": {"datavalue": {"value": {"id": "Q1"}}}}],
                   "P31": [{"mainsnak": {"snaktype": "novalue"}},
                           {"mainsnak": {"datavalue": {"value": {"id": "Q2"}}}}]}}))
    assert wikidata.parents("Q5") == ["Q1", "Q2"]
