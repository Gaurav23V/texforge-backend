from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    supabase_url: str = "http://localhost:54321"
    supabase_service_key: str = "test-key"
    max_concurrent_compiles: int = 2
    compile_timeout_seconds: int = 15
    semaphore_wait_timeout_seconds: int = 10
    max_tex_size_bytes: int = 1_000_000  # 1MB
    max_log_response_chars: int = 20_000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def override_settings(settings: Settings) -> None:
    """Override settings for testing."""
    global _settings
    _settings = settings
