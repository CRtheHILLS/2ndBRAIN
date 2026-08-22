import json
from . import store
LEVELS = ("초등", "일반", "전문")
def _f(): return store.profile_dir() / "levels.json"
def _load(): return json.loads(_f().read_text("utf-8")) if _f().exists() else {}
def get_level(topic: str): return _load().get(topic)
def set_level(topic: str, level: str) -> None:
    if level not in LEVELS: raise ValueError(level)
    d = _load(); d[topic] = level
    _f().write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
