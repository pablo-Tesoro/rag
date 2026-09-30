"""Application settings, read from environment variables (and `.env` in development).

Every tunable lives here so behaviour can change per environment without touching code.
New settings are added as the phases that need them land.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from bank_assistant.retrieval import RetrievalMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"
    log_pseudonym_key: SecretStr = SecretStr("dev-only-change-me")
    database_url: str = "postgresql://olvessa:olvessa-dev-only@localhost:5432/olvessa"

    data_dir: Path = Field(
        default=Path("data"),
        description="Root of the fictitious data (corpus, employees, core banking).",
    )

    # --- Embeddings (local, CPU) ---
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_query_prefix: str = "query: "
    embedding_document_prefix: str = "passage: "

    # --- Chunking ---
    chunk_max_tokens: int = Field(default=380, gt=0)
    chunk_overlap_tokens: int = Field(default=60, ge=0)

    # --- Retrieval ---
    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID
    retrieval_top_k: int = Field(default=5, gt=0)
    retrieval_candidates: int = Field(default=20, gt=0, description="Per-list depth before RRF.")
    rrf_k: int = Field(default=60, gt=0)

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
