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


AREA_NAMES = {
    "A": "수학", "B": "물리·우주", "C": "화학·재료", "D": "생명·의학", "E": "지구·환경",
    "F": "기술·공학", "G": "정보·컴퓨팅", "H": "인간·마음·뇌", "I": "사회·경제·경영",
    "J": "역사·고고", "K": "철학·종교", "L": "언어·문학", "M": "예술·음악", "N": "생활·건강·운동",
    "O": "동물·반려", "P": "법·정치·교육", "Z": "메타(학습법·도구·2nd BRAIN 자체)",
}


def test_shipped_file_metadata_and_area_names():
    data = frame.load()
    assert data["status"] == "draft" and data["version"] == 1
    assert {a["code"]: a["name_ko"] for a in data["areas"]} == AREA_NAMES
    assert all(f["deprecated_to"] is None for f in frame.fields().values())


def _fake(areas):
    return {"version": 1, "status": "draft", "areas": areas}


def _f(code, dep=None, **kw):
    return {"code": code, "name_ko": code, "name_en": code, "deprecated_to": dep, **kw}


def _area(code, fields):
    return {"code": code, "name_ko": "", "name_en": "", "fields": fields}


def test_validate_negative_paths(monkeypatch):
    def run(areas):
        monkeypatch.setattr(frame, "load", lambda: _fake(areas))
        return frame.validate()

    assert any("duplicate code" in p for p in run([_area("B", [_f("B1"), _f("B1")])]))
    assert any("unknown" in p for p in run([_area("B", [_f("B1", "B9")])]))
    assert any("does not belong" in p for p in run([_area("B", [_f("C1")])]))
    assert any("itself" in p for p in run([_area("B", [_f("B1", "B1")])]))
    assert any("cycle" in p for p in run([_area("B", [_f("B1", "B2"), _f("B2", "B1")])]))
    assert any("bad code" in p for p in run([_area("B", [_f("Bx")])]))
    assert any("duplicate area" in p for p in run([_area("B", []), _area("B", [])]))


def test_fallback_and_note_in_prompt_list(monkeypatch):
    shipped = frame.field_prompt_list()
    assert frame.FALLBACK_CODE == "Z6" and frame.fields()["Z6"]["fallback"] is True
    assert "Z6" not in shipped
    assert "B6 유체·음향 (Fluids & Acoustics) — 물리 원리; 음향기기는 F10" in shipped.splitlines()
    monkeypatch.setattr(frame, "load", lambda: _fake([_area("Z", [
        _f("Z1", note="힌트"), _f("Z6", fallback=True)])]))
    assert frame.field_prompt_list() == "Z1 Z1 (Z1) — 힌트"


def test_reorganised_areas():
    f = frame.fields()
    assert f["J1"]["name_ko"] == "한국사" and f["K9"]["name_ko"] == "이슬람·유대교"
    assert f["Z2"]["name_ko"].startswith("도구·소프트웨어")
    assert all(len(x.get("note", "")) <= 40 for x in f.values())
