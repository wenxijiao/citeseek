"""Application configuration.

Environment variables (and .env) hold secrets and machine-level defaults;
user-tweakable options (active provider/model, target language) live in the
settings table and override these at runtime via Engine.get_settings().
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
    )

    # LLM provider keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"

    # Active LLM selection (overridable per-request and via settings table)
    citeseek_llm_provider: str = "anthropic"
    citeseek_llm_model: str = ""

    # Scholarly APIs
    s2_api_key: str = ""
    openalex_mailto: str = ""

    # Storage
    citeseek_db_path: str = "var/citeseek.db"

    # Pipeline knobs
    first_pass_keep: int = 30
    # Backward snowballing: mine references of the top-k first-pass candidates
    citation_expansion: bool = True
    citation_seeds: int = 10
    fulltext_top_n: int = 5
    passages_per_paper: int = 3
    candidates_returned: int = 10

    @property
    def db_path(self) -> Path:
        p = Path(self.citeseek_db_path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def var_dir(self) -> Path:
        return self.db_path.parent

    @property
    def fulltext_dir(self) -> Path:
        return self.var_dir / "fulltext"

    @property
    def models_dir(self) -> Path:
        return self.var_dir / "models"

    @property
    def pdf_dir(self) -> Path:
        return self.var_dir / "pdfs"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
