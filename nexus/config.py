"""Application configuration via Pydantic settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    nexus_env: str = Field(default="development", alias="NEXUS_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # LLM
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")

    # Database
    postgres_url: str = Field(
        default="postgresql+asyncpg://nexus:nexus@localhost:5432/nexus",
        alias="POSTGRES_URL",
    )

    # ChromaDB
    chroma_host: str = Field(default="localhost", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8000, alias="CHROMA_PORT")

    # Execution
    step_timeout_seconds: int = Field(default=30, alias="STEP_TIMEOUT_SECONDS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")

    # Observability
    prometheus_port: int = Field(default=9090, alias="PROMETHEUS_PORT")

    @property
    def is_test(self) -> bool:
        return self.nexus_env == "test"

    @property
    def llm_available(self) -> bool:
        return bool(self.openai_api_key and not self.openai_api_key.startswith("sk-test"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
