"""
config.py — Centralised settings using pydantic-settings.
All values are loaded from environment variables or .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Telegram ──
    telegram_bot_token: str = Field(..., description="Bot token from @BotFather")
    telegram_admin_ids: List[int] = Field(default_factory=list, description="Comma-separated admin user IDs")

    # ── Channels ──
    telegram_client_channel_id: int = Field(0)
    telegram_agent_channel_id: int = Field(0)
    telegram_payment_log_channel_id: int = Field(0)

    # ── Redis ──
    redis_url: str = Field("redis://localhost:6379/0")

    # ── OpenAI ──
    openai_api_key: str = Field("")
    openai_model: str = Field("gpt-4o-mini")

    # ── App ──
    webhook_url: str = Field("")
    app_host: str = Field("0.0.0.0")
    app_port: int = Field(8000)
    debug: bool = Field(False)

    # ── Payment ──
    upi_id: str = Field("")
    payment_verification_enabled: bool = Field(True)


settings = Settings()
