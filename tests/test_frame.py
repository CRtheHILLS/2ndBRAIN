import pytest

from brain import frame


@pytest.fixture(autouse=True)
def _clear():
    frame.load.cache_clear()
    yield
    frame.load.cache_clear()


def test_taxonomy_has_17_areas_and_unique_codes():
    data = frame.load()
    areas = data["areas"]
    assert {a["code"] for a in areas} == set("ABCDEFGHIJKLMNOPZ")
    codes = []
    for a in areas:
        assert 6 <= len(a["fields"]) <= 10, a["code"]
        for f in a["fields"]:
            assert f["code"].startswith(a["code"])
            codes.append(f["code"])
    assert len(codes) == len(set(codes))
    assert 120 <= len(codes) <= 170


def test_validate_is_clean_on_shipped_file():
    assert frame.validate() == []


def test_resolve_follows_deprecated_to(monkeypatch):
    fake = {"version": 1, "status": "draft", "areas": [
        {"code": "B", "name_ko": "b", "name_en": "b", "fields": [
            {"code": "B4", "name_ko": "양자", "name_en": "Quantum", "deprecated_to": None},
            {"code": "B9", "name_ko": "옛", "name_en": "Old", "deprecated_to": "B4"}]},
        {"code": "X", "name_ko": "x", "name_en": "x", "fields": [
            {"code": "X1", "name_ko": "a", "name_en": "a", "deprecated_to": "X2"},
            {"code": "X2", "name_ko": "b", "name_en": "b", "deprecated_to": "X1"}]},
    ]}
    monkeypatch.setattr(frame, "load", lambda: fake)
    assert frame.resolve_code("B9") == "B4"
    assert frame.resolve_code("B4") == "B4"
    assert frame.resolve_code("X1") == "X1"
    assert frame.is_valid_code("B9") and not frame.is_valid_code("Q9")
    assert frame.area_of("B9") == "B"


def test_domain_to_area_mapping():
    expected = {"과학": "B", "역사": "J", "종교": "K", "철학": "K", "심리": "H",
                "경제": "I", "기술": "F", "예술": "M", "동물": "O", "건강": "N", "기타": "Z"}
    for d, a in expected.items():
        assert frame.domain_to_area(d) == a
    assert frame.domain_to_area("모름") == "Z"


def test_field_prompt_list_excludes_deprecated(monkeypatch):
    fake = {"version": 1, "status": "draft", "areas": [
        {"code": "B", "name_ko": "b", "name_en": "b", "fields": [
            {"code": "B4", "name_ko": "양자", "name_en": "Quantum", "deprecated_to": None},
            {"code": "B9", "name_ko": "옛", "name_en": "Old", "deprecated_to": "B4"}]}]}
    monkeypatch.setattr(frame, "load", lambda: fake)
    assert frame.field_prompt_list() == "B4 양자 (Quantum)"


def test_shipped_has_spec_examples():
    f = frame.fields()
    assert f["B4"]["name_ko"] == "양자" and f["B4"]["area"] == "B"
    assert f["Z3"]["name_ko"] == "2nd BRAIN 자체"
    assert "B4 양자 (Quantum)" in frame.field_prompt_list().splitlines()
