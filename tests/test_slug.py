from brain.slug import slugify


def test_korean_title_kept():
    assert slugify("코스모스 (칼 세이건)") == "코스모스-칼-세이건"


def test_english_title_lowercased():
    assert slugify("The Selfish Gene!") == "the-selfish-gene"


def test_max_length():
    assert len(slugify("a" * 100)) <= 60
