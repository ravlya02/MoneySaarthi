from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-pro"
    gemini_embedding_model: str = "gemini-embedding-2"

    qdrant_url: str = ""
    qdrant_api_key: str = ""

    web_search_api_key: str = ""
    web_search_provider: str = "tavily"

    assessment_year: str = "AY 2026-27"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
