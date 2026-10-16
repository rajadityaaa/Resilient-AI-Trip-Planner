"""
Centralised configuration management using pydantic-settings.
Loads environment variables from .env and system environment with safe defaults.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import List, Union

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # API Keys (Stored as SecretStr so they are never printed or leaked in logs)
    GROQ_API_KEY: SecretStr = SecretStr("")
    OPENROUTER_API_KEY: SecretStr = SecretStr("")
    FOURSQUARE_API_KEY: SecretStr = SecretStr("")

    # Persistence
    DATABASE_URL: str = "data/travel.db"

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:8501",
        "http://localhost:3000",
        "http://127.0.0.1:8501",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
    ]

    # Performance & Concurrency controls
    LLM_MAX_CONCURRENT: int = 3
    LLM_DEADLINE_S: float = 22.0
    AGENT_TIMEOUT_S: float = 48.0

    # API Protection & Rate Limiting
    RATE_LIMIT_PER_MIN: int = 5
    DAILY_JOB_LIMIT: int = 100
    PORT: int = 8000
    ENABLE_METRICS: bool = False

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v_str = v.strip()
            if v_str.startswith("[") and v_str.endswith("]"):
                try:
                    return json.loads(v_str)
                except Exception:
                    pass
            return [origin.strip() for origin in v_str.split(",") if origin.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
