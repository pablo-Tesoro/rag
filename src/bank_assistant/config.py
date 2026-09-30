"""Application settings, read from environment variables (and `.env` in development).

Every tunable lives here so behaviour can change per environment without touching code.
New settings are added as the phases that need them land.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"
    log_pseudonym_key: SecretStr = SecretStr("dev-only-change-me")
    database_url: str = "postgresql://olvessa:olvessa-dev-only@localhost:5432/olvessa"

    data_dir: Path = Field(
        default=Path("data"),
        description="Root of the fictitious data (corpus, employees, core banking).",
    )

    @property
    def corpus_dir(self) -> Path:
        return self.data_dir / "corpus"

    @property
    def employees_file(self) -> Path:
        return self.data_dir / "employees.json"

    @property
    def offices_file(self) -> Path:
        return self.data_dir / "core_banking" / "offices.json"

    @property
    def operations_file(self) -> Path:
        return self.data_dir / "core_banking" / "operations.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
