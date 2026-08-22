import pytest
from brain import llm


class _Block:
    def __init__(self, type_, text=None):
        self.type = type_
        if text is not None:
            self.text = text


class _Response:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


def test_first_text_returns_first_text_block_skipping_others():
    r = _Response([_Block("thinking"), _Block("text", "hello"), _Block("text", "second")])
    assert llm._first_text(r) == "hello"


def test_first_text_raises_on_max_tokens():
    r = _Response([_Block("text", "cut off")], stop_reason="max_tokens")
    with pytest.raises(RuntimeError, match="model output truncated"):
        llm._first_text(r)
