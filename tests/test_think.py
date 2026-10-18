import json

import pytest
from pydantic import BaseModel

from brain import think as T


def _keys(monkeypatch, a="", g="", x=""):
    from brain import config
    monkeypatch.setenv("ANTHROPIC_API_KEY", a)
    monkeypatch.setenv("GEMINI_API_KEY", g)
    monkeypatch.setenv("XAI_API_KEY", x)
    config.get_settings.cache_clear()


def _boom(*a, **k):
    raise RuntimeError("boom")


def test_parse_json_salvages_fenced_and_prefixed():
    assert T.parse_json('설명:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert T.parse_json("no json") is None


def test_chain_skips_providers_without_key_and_falls_through(data_dir, monkeypatch):
    _keys(monkeypatch, g="g")
    monkeypatch.setattr(T, "_anthropic", _boom)
    monkeypatch.setattr(T, "_gemini", lambda s, u, m: ('{"ok": true}', 10, 5))
    monkeypatch.setattr(T, "_xai", _boom)
    r = T.think("classify", "s", "u")
    assert r.provider == "gemini"
    assert r.data == {"ok": True}
    assert (r.input_tokens, r.output_tokens) == (10, 5)
    assert T.daily_count() == 1


def test_chain_raises_unavailable_with_all_reasons(data_dir, monkeypatch):
    _keys(monkeypatch, g="g")
    monkeypatch.setattr(T, "_anthropic", _boom)
    monkeypatch.setattr(T, "_gemini", _boom)
    monkeypatch.setattr(T, "_xai", _boom)
    with pytest.raises(T.ThinkUnavailable) as e:
        T.think("classify", "s", "u")
    assert len(e.value.reasons) >= 2
    assert any("no key" in r for r in e.value.reasons)


def test_retry_once_on_bad_json_then_next_provider(data_dir, monkeypatch):
    _keys(monkeypatch, a="a", g="g")
    calls = []

    def anth(s, u, m):
        calls.append(u)
        return ("oops" if len(calls) == 1 else "still"), 1, 1

    monkeypatch.setattr(T, "_anthropic", anth)
    monkeypatch.setattr(T, "_gemini", lambda s, u, m: ('{"x":1}', 1, 1))
    r = T.think("classify", "s", "u")
    assert r.provider == "gemini"
    assert len(calls) == 2


class _N(BaseModel):
    n: int


def test_schema_validation(data_dir, monkeypatch):
    _keys(monkeypatch, a="a", g="g")
    monkeypatch.setattr(T, "_anthropic", lambda s, u, m: ('{"n": "a"}', 1, 1))
    monkeypatch.setattr(T, "_gemini", lambda s, u, m: ('{"n": 3}', 1, 1))
    r = T.think("classify", "s", "u", _N)
    assert r.data["n"] == 3
    assert r.provider == "gemini"


def test_daily_cap_blocks(data_dir, monkeypatch):
    _keys(monkeypatch, a="a")
    monkeypatch.setenv("THINK_DAILY_CAP", "1")
    from brain import config
    config.get_settings.cache_clear()
    T.record_usage("classify", "anthropic", "m", 1, 1, 0.1)
    assert T.daily_count() == 1
    monkeypatch.setattr(T, "_anthropic", lambda s, u, m: ('{"a":1}', 1, 1))
    with pytest.raises(T.ThinkUnavailable) as e:
        T.think("classify", "s", "u")
    assert "daily cap" in e.value.reasons


def test_smart_kind_picks_smart_model(data_dir, monkeypatch):
    _keys(monkeypatch, a="a")
    seen = []

    def anth(s, u, m):
        seen.append(m)
        return '{"a":1}', 1, 1

    monkeypatch.setattr(T, "_anthropic", anth)
    T.think("teach", "s", "u")
    T.think("classify", "s", "u")
    assert seen == ["claude-sonnet-5-5", "claude-haiku-5-5"]


def test_complete_text_returns_plain_text(data_dir, monkeypatch):
    _keys(monkeypatch, x="x")
    monkeypatch.setattr(T, "_xai", lambda s, u, m: ("hello", 3, 4))
    assert T.complete_text("s", "u", False) == ("hello", "xai", "grok-4-1-fast-non-reasoning", 3, 4)


def test_gemini_adapter_rest(data_dir, monkeypatch):
    import httpx
    import respx
    _keys(monkeypatch, g="gk")
    with respx.mock:
        route = respx.post("https://generativelanguage.googleapis.com/v1beta/models/gm:generateContent").mock(
            return_value=httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
                "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 2}}))
        assert T._gemini("sys", "usr", "gm") == ("hi", 7, 2)
        body = json.loads(route.calls[0].request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert route.calls[0].request.url.params["key"] == "gk"


def test_xai_adapter_and_non2xx(data_dir, monkeypatch):
    import httpx
    import respx
    _keys(monkeypatch, x="xk")
    with respx.mock:
        respx.post("https://api.x.ai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": "yo"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 6}}))
        assert T._xai("s", "u", "m") == ("yo", 5, 6)
    with respx.mock:
        respx.post("https://api.x.ai/v1/chat/completions").mock(return_value=httpx.Response(500))
        with pytest.raises(httpx.HTTPStatusError):
            T._xai("s", "u", "m")
