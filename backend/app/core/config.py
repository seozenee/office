"""Application settings. Every secret comes from the environment — never from code."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"),
                                      env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    app_name: str = "Personal AI Office"
    environment: str = "development"

    # Storage
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'office.db'}"
    workspace_dir: Path = BACKEND_DIR / "data" / "workspace"

    # Security
    secret_key: str = Field(default="change-me-in-production", min_length=8)
    auth_enabled: bool = True
    admin_username: str = "ceo"
    admin_password: str = "office-dev-password"
    token_ttl_hours: int = 72
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # LLM
    anthropic_api_key: str | None = None
    llm_provider: str = "auto"  # auto | anthropic | offline
    model_fast: str = "claude-haiku-4-5"
    model_reasoning: str = "claude-opus-5"
    model_coding: str = "claude-opus-5"
    model_long_context: str = "claude-opus-5"
    model_multimodal: str = "claude-opus-5"
    llm_max_tokens: int = 16000

    # Web research
    search_provider: str = "auto"  # auto | tavily | brave | serper | searxng | fixture | none
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    serper_api_key: str | None = None
    searxng_url: str | None = None
    fixture_search_file: str | None = None  # JSON file mapping queries→results (tests / offline demos)
    http_timeout: float = 20.0
    max_sources_per_task: int = 12
    fetch_user_agent: str = "PersonalAIOffice/1.0 (+research bot)"
    fetch_allow_private_network: bool = False  # SSRF guard; enable only for local fixtures/tests
    fetch_max_bytes: int = 25_000_000
    fetch_mirror_dir: str | None = None  # research snapshot replay: index.json {url: {"file","content_type"}}

    # Browser / computer agent (Playwright)
    browser_enabled: bool = True
    browser_allowed_domains: str = ""  # comma-separated allow-list; empty = any public site
    browser_render_fallback: bool = True  # render JS pages with the browser when plain fetch finds no content

    # Embeddings
    embedding_provider: str = "hash"  # hash | voyage
    voyage_api_key: str | None = None
    embedding_dim: int = 384

    # Jobs
    inline_worker: bool = True  # run a worker thread inside the API process
    worker_poll_seconds: float = 1.0

    timezone: str = "Asia/Seoul"  # for schedules and briefings

    # Office presentation pacing: seconds between meeting utterances / pipeline stages so the CEO can
    # watch employees walk to meetings and talk. 0 disables (tests).
    office_pace_seconds: float = 1.0

    # Research quality control
    stale_after_years: int = 3
    min_verified_ratio: float = 0.5
    max_research_rounds: int = 2

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.workspace_dir.mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite:///"):
        Path(s.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return s
