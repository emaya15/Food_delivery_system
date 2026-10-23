"""Application settings loaded from environment variables / ``.env``."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. No secrets are hard-coded here."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Food Delivery System"
    debug: bool = False

    # Required - there are intentionally no defaults for secrets.
    database_url: str
    jwt_secret_key: str

    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    timezone: str = "Asia/Kolkata"
    scheduler_enabled: bool = True
    cors_origins: str = ""  # comma separated list; empty disables CORS

    @field_validator("jwt_secret_key")
    @classmethod
    def _secret_must_be_strong(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return value

    @property
    def cors_origin_list(self) -> "list[str]":
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()  # type: ignore[call-arg]
