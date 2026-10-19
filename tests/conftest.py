import socket

import pytest
from brain import config
from brain.connectors import base


@pytest.fixture(autouse=True)
def _offline_public_dns():
    """No DNS in tests: every host 'resolves' to a public address (SSRF tests swap this back).

    Set by hand, not via ``monkeypatch``, so other files' autouse fixtures keep their teardown order.
    """
    saved = base._getaddrinfo
    base._getaddrinfo = lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
    yield
    base._getaddrinfo = saved


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
