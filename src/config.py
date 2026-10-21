"""Configuration module using Pydantic Settings."""

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable overrides."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM API Keys
    GROQ_API_KEY: str | None = Field(
        default=None, validation_alias=AliasChoices("GROQ_API_KEY", "groq_api_key")
    )
    GEMINI_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "gemini_api_key", "google_api_key"
        ),
    )
    OPENAI_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    ANTHROPIC_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "anthropic_api_key"),
    )

    # Provider & Model Settings
    LLM_PROVIDER: Literal["groq", "gemini", "openai", "anthropic", "ollama", "mock"] = Field(
        default="gemini",
        description="Active LLM provider for agent steps",
        validation_alias=AliasChoices("LLM_PROVIDER", "llm_provider"),
    )
    LLM_MODEL: str | None = Field(
        default=None,
        description="Global model override from .env (e.g. LLM_MODEL=qwen/qwen3.8-27b)",
        validation_alias=AliasChoices("LLM_MODEL", "llm_model", "MODEL_NAME", "model_name"),
    )
    GROQ_MODEL: str = Field(
        default="qwen/qwen3.8-27b",
        description="Active Groq model from .env",
        validation_alias=AliasChoices("GROQ_MODEL", "groq_model"),
    )
    GEMINI_MODEL: str = Field(
        default="gemini-3.5-flash",
        description="Active Gemini model from .env",
        validation_alias=AliasChoices("GEMINI_MODEL", "gemini_model"),
    )
    OLLAMA_MODEL: str = Field(
        default="llama3.1:8b",
        description="Active Ollama model from .env",
        validation_alias=AliasChoices("OLLAMA_MODEL", "ollama_model"),
    )
    OPENAI_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Active OpenAI model",
        validation_alias=AliasChoices("OPENAI_MODEL", "openai_model"),
    )
    ANTHROPIC_MODEL: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Active Anthropic model",
        validation_alias=AliasChoices("ANTHROPIC_MODEL", "anthropic_model"),
    )
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Search & Tool Configuration
    TAVILY_API_KEY: str | None = Field(default=None)
    SEARCH_ENGINE: Literal["auto", "tavily", "duckduckgo", "mock"] = Field(
        default="auto",
        description="Search engine to use: 'auto' (Tavily if key present else DDG), 'tavily', 'duckduckgo', or 'mock'",
    )
    SEARCH_MAX_RESULTS_PER_QUERY: int = Field(default=5)
    SCRAPER_TIMEOUT_SECONDS: float = Field(default=6.0)
    SCRAPER_MAX_WORDS_PER_PAGE: int = Field(default=2500)
    MAX_CITATIONS_PER_DOMAIN: int = Field(default=2)

    # Jina Reader Configuration
    JINA_API_KEY: str | None = Field(default=None)
    ENABLE_JINA_FALLBACK: bool = Field(
        default=True,
        description="Whether to fall back to Jina Reader (r.jina.ai) when direct scraping is blocked.",
    )

    # Playwright Headless Stealth Scraper Configuration
    ENABLE_PLAYWRIGHT_FALLBACK: bool = Field(
        default=True,
        description="Whether to fall back to headless Playwright stealth browser when direct scraping and Jina fail (e.g. anti-bot 403, Cloudflare, SPAs).",
    )
    PLAYWRIGHT_TIMEOUT_SECONDS: float = Field(
        default=12.0,
        description="Timeout in seconds for Playwright headless page render.",
    )
    PLAYWRIGHT_HEADLESS: bool = Field(
        default=True,
        description="Whether to run Playwright in headless mode.",
    )

    # Developer Community / Hacker News Configuration
    ENABLE_HACKER_NEWS: bool = Field(
        default=True,
        description="Whether to query Hacker News for real-world developer discussions and post-mortems.",
    )
    HN_MAX_RESULTS: int = Field(default=2)

    # Persistence (Redis)
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    REPORT_RETENTION_SECONDS: int = Field(
        default=86400,
        description="TTL in seconds for ephemeral research run data (reports, events, steps, metadata). Set to 0 to disable auto-cleanup.",
        validation_alias=AliasChoices("REPORT_RETENTION_SECONDS", "report_retention_seconds"),
    )

    # Distributed Worker Configuration
    WORKER_MODE: Literal["decoupled", "embedded"] = Field(
        default="decoupled",
        description="Execution mode: 'decoupled' enqueues to Redis queue; 'embedded' runs in-process.",
        validation_alias=AliasChoices("WORKER_MODE", "worker_mode"),
    )
    WORKER_CONCURRENCY: int = Field(
        default=2,
        description="Number of concurrent research jobs per worker node.",
        validation_alias=AliasChoices("WORKER_CONCURRENCY", "worker_concurrency"),
    )

    # Production Budget & Guardrails
    MAX_SUB_QUESTIONS: int = 4
    MAX_SEARCHES_PER_SUB_QUESTION: int = 3
    MAX_BUDGET_TOKENS: int = 150000
    MAX_WALL_CLOCK_SECONDS: int = 240
    MAX_REVISIONS_PER_SUBQUESTION: int = 1

    # Runtime Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"


# Global singleton settings instance
settings = Settings()
