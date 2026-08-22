import pytest
from brain import levels

def test_default_none_then_set(data_dir):
    assert levels.get_level("양자역학") is None
    levels.set_level("양자역학", "초등")
    assert levels.get_level("양자역학") == "초등"

def test_invalid_level(data_dir):
    with pytest.raises(ValueError):
        levels.set_level("x", "신")
