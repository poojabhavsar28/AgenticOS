"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AgenticOS"
    app_env: str = "development"
    log_level: str = "INFO"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:3b"
    ollama_timeout_seconds: float = Field(default=120.0, gt=0, le=900)
    run_timeout_seconds: float = Field(default=300.0, gt=0, le=3600)
    max_concurrent_runs: int = Field(default=2, ge=1, le=32)
    workspace_root: Path = Path("./workspace")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
