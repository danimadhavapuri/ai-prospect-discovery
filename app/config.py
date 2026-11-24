"""Application configuration and environment settings.

Production-grade settings management using Pydantic Settings v2.
Secrets are loaded strictly from environment variables or .env file.
"""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for AI Prospect Discovery API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # API Keys
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key for structured query understanding and synthesis.",
    )
    tavily_api_key: str = Field(
        default="",
        description="Tavily Search API key for real-time multi-platform prospect search.",
    )

    # LLM Model Config
    gemini_primary_model: str = Field(
        default="gemini-2.5-flash",
        description="Primary fast LLM for query understanding and structured output.",
    )
    gemini_fallback_model: str = Field(
        default="gemini-2.5-flash-lite",
        description="Fallback lightweight model if primary encounters rate limits.",
    )

    # In-Memory TTL Cache Configuration
    cache_ttl_seconds: int = Field(
        default=3600,
        description="TTL in seconds for query understanding and search result cache (1 hour).",
    )
    cache_maxsize: int = Field(
        default=1000,
        description="Maximum entries in in-memory TTL cache.",
    )

    # Search & Network Limits
    search_timeout_seconds: float = Field(
        default=10.0,
        description="Timeout in seconds for outbound Tavily Search API calls.",
    )
    http_timeout_seconds: float = Field(
        default=5.0,
        description="Timeout in seconds for SSRF-protected safe HTTP metadata fetches.",
    )
    max_search_concurrency: int = Field(
        default=5,
        description="Maximum concurrent outbound Tavily requests per discovery run.",
    )
    max_tavily_queries_per_request: int = Field(
        default=6,
        description="Maximum targeted/grouped search queries generated per request to preserve credits.",
    )

    # SSRF & Data Safety
    max_response_bytes: int = Field(
        default=1_048_576,  # 1 MB
        description="Maximum byte limit for outbound HTTP response inspection.",
    )

    # Server Configuration
    app_host: str = Field(default="0.0.0.0", description="FastAPI host binding.")
    app_port: int = Field(default=4000, description="FastAPI port binding.")
    environment: str = Field(default="development", description="Runtime environment.")

    @property
    def has_gemini_key(self) -> bool:
        """Check if Gemini API key is configured and non-empty."""
        return bool(self.gemini_api_key and self.gemini_api_key.strip())

    @property
    def has_tavily_key(self) -> bool:
        """Check if Tavily API key is configured and non-empty."""
        return bool(self.tavily_api_key and self.tavily_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
