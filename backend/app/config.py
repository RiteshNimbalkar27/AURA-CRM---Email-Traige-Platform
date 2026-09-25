"""
AURA Application Configuration
All settings loaded from environment variables / .env file.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Search for .env in current dir, then parent (project root)
_here = Path(__file__).parent          # backend/app/
_env_candidates = [
    _here / ".." / ".." / ".env",      # project root (d:\Code\EDAI Email\.env)
    _here / ".." / ".env",             # backend/.env
    Path(".env"),                       # cwd/.env
]
_env_file = next((str(p.resolve()) for p in _env_candidates if p.exists()), ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://aura:aura_dev_password@localhost:5432/aura_db"
    postgres_db: str = "aura_db"
    postgres_user: str = "aura"
    postgres_password: str = "aura_dev_password"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT Auth
    secret_key: str = "dev_secret_key_change_in_production_at_least_32_chars"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # OpenRouter LLM (DeepSeek V4 Flash 0731 by default)
    openrouter_api_key: str = "not_set"
    llm_model: str = "deepseek/deepseek-v4-flash-0731"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_cache_dir: str = "./data/model_cache"

    # Web Enrichment
    enrichment_review_url: str = "https://www.g2.com/products/nexus-software"
    enrichment_competitor_url: str = "https://competitor.example.com/pricing"

    # App
    environment: str = "development"
    log_level: str = "INFO"
    synthetic_data_only: bool = True

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql", "sqlite")):
            raise ValueError("DATABASE_URL must be a PostgreSQL or SQLite connection string")
        return v

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def is_testing(self) -> bool:
        return self.environment.lower() == "testing"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
