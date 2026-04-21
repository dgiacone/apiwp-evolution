from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    evolution_base_url: str = "http://127.0.0.1:8080"
    evolution_api_key: str = ""
    webhook_public_url: str = ""
    auto_session_phone: str = ""
    auto_session_instance_name: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
