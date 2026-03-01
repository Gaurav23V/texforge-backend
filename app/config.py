from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    max_concurrent_compiles: int = 2
    compile_timeout_seconds: int = 15
    semaphore_wait_timeout_seconds: int = 10
    max_tex_size_bytes: int = 1_000_000  # 1MB
    max_log_response_chars: int = 20_000

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
