import pytest
from brain import config


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_TOKEN", "test-token")
    monkeypatch.setenv("CANON_WIKIDATA", "0")
    for key in ("GEMINI_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv(key, "")  # a real key in the developer's shell must never reach tests
    config.get_settings.cache_clear()
    return tmp_path
