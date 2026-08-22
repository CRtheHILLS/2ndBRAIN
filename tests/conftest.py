import pytest
from brain import config


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_TOKEN", "test-token")
    config.get_settings.cache_clear()
    return tmp_path
