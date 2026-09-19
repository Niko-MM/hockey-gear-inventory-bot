from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(default="")
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    db_path: str = str(PROJECT_ROOT / "data" / "bot.db")
    income_sheet_url: str = ""

    @field_validator("admin_ids", mode="before")
    @classmethod
    def split_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        return value

    @field_validator("bot_token")
    @classmethod
    def require_bot_token(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("BOT_TOKEN пустой. Заполни его в файле .env")
        return token

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


settings = Settings()
