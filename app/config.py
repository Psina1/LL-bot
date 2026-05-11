from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_admin_ids: str = Field(default="", alias="TELEGRAM_ADMIN_IDS")

    database_url: str = Field(alias="DATABASE_URL")
    postgres_db: str = Field(default="leader_bot", alias="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(default="postgres", alias="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")

    llm_provider: Literal["openai", "mock"] = Field(default="openai", alias="LLM_PROVIDER")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_chat_model: str = Field(default="gpt-4o-mini", alias="OPENAI_CHAT_MODEL")
    openai_embedding_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")

    bot_mode: Literal["polling"] = Field(default="polling", alias="BOT_MODE")
    env: str = Field(default="local", alias="ENV")

    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    uploads_dir: Path = Field(default=Path("./data/uploads"), alias="UPLOADS_DIR")
    materials_dir: Path = Field(default=Path("./data/materials"), alias="MATERIALS_DIR")

    max_file_size_mb: int = Field(default=20, alias="MAX_FILE_SIZE_MB")
    allowed_extensions: str = Field(default="pdf,docx,pptx,txt", alias="ALLOWED_EXTENSIONS")
    max_context_chunks: int = Field(default=8, alias="MAX_CONTEXT_CHUNKS")
    max_context_chars: int = Field(default=12000, alias="MAX_CONTEXT_CHARS")
    max_user_questions_per_minute: int = Field(default=10, alias="MAX_USER_QUESTIONS_PER_MINUTE")
    temperature: float = Field(default=0.2, alias="TEMPERATURE")
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS")

    vm_rub_per_hour: float = Field(default=4.60, alias="VM_RUB_PER_HOUR")
    vm_billing_started_at: str | None = Field(default=None, alias="VM_BILLING_STARTED_AT")
    usd_rub_rate: float = Field(default=90.0, alias="USD_RUB_RATE")
    openai_chat_input_usd_per_1m: float = Field(default=0.15, alias="OPENAI_CHAT_INPUT_USD_PER_1M")
    openai_chat_output_usd_per_1m: float = Field(default=0.60, alias="OPENAI_CHAT_OUTPUT_USD_PER_1M")
    openai_embedding_usd_per_1m: float = Field(default=0.02, alias="OPENAI_EMBEDDING_USD_PER_1M")
    yandexgpt_input_rub_per_1k: float = Field(default=0.20, alias="YANDEXGPT_INPUT_RUB_PER_1K")
    yandexgpt_output_rub_per_1k: float = Field(default=0.20, alias="YANDEXGPT_OUTPUT_RUB_PER_1K")
    yandex_embedding_rub_per_1k: float = Field(default=0.0101, alias="YANDEX_EMBEDDING_RUB_PER_1K")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @computed_field(return_type=list[int])
    @property
    def admin_ids(self) -> list[int]:
        if not self.telegram_admin_ids.strip():
            return []
        return [int(admin_id.strip()) for admin_id in self.telegram_admin_ids.split(",") if admin_id.strip()]

    @computed_field(return_type=set[str])
    @property
    def extensions_set(self) -> set[str]:
        return {ext.strip().lower() for ext in self.allowed_extensions.split(",") if ext.strip()}

    @computed_field(return_type=int)
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.materials_dir.mkdir(parents=True, exist_ok=True)
    return settings
