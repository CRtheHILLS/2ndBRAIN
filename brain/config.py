from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_dir: Path = Path("/data")
    brain_token: str = "change-me"
    anthropic_api_key: str = ""
    model_fast: str = "claude-haiku-5-5"
    model_smart: str = "claude-sonnet-5-5"
    gemini_api_key: str = ""
    gemini_model_fast: str = "gemini-3.1-flash-lite"
    gemini_model_smart: str = "gemini-3.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    xai_api_key: str = ""
    xai_model_fast: str = "grok-4-1-fast-non-reasoning"
    xai_model_smart: str = "grok-4.3"
    think_providers: str = "anthropic,gemini,xai"
    think_daily_cap: int = 200
    think_retry_minutes: int = 30
    think_retry_hours: int = 48
    quest_max_think_calls: int = 40
    quest_max_sources: int = 45
    quest_max_doc_chars: int = 60000
    quest_max_pdf_pages: int = 40
    quest_max_minutes: int = 30
    quest_quota_per_dot: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
