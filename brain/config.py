from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_dir: Path = Path("/data")
    brain_token: str = "change-me"
    anthropic_api_key: str = ""
    model_fast: str = "claude-haiku-4-5-20251001"
    model_smart: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
