"""Pydantic schemas and data contracts.

Enforces strict request validation, structured output contracts,
and typed intermediate models for candidate profiles and search results.
"""

from typing import Literal
from pydantic import BaseModel, Field, field_validator

# Exact platform literals mandated by specification
SocialPlatform = Literal[
    "Google",
    "LinkedIn",
    "X",
    "YouTube",
    "Instagram",
    "WhatsApp",
    "Facebook",
    "Email",
    "Threads",
]


class SocialLink(BaseModel):
    """Verified platform link or contact reference."""

    platform: SocialPlatform = Field(
        ...,
        description="Standardized platform name matching the exact API specification.",
    )
    link: str = Field(
        ...,
        description="Verified URL or mailto: link for this platform.",
    )


class Prospect(BaseModel):
    """Verified prospect profile consolidating discovered signals."""

    name: str = Field(
        ...,
        description="Verified individual or organization name extracted from public sources.",
    )
    location: str = Field(
        default="",
        description="Verified city, state/country when available; empty if unknown.",
    )
    social_link: list[SocialLink] = Field(
        default_factory=list,
        description="List of verified social and contact links for the prospect.",
    )


class DiscoveryRequest(BaseModel):
    """Inbound prospect discovery request payload."""

    query: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="Natural language query describing desired prospects, roles, niches, and locations.",
        examples=["Find AI founders in San Francisco with LinkedIn and Twitter"],
    )

    @field_validator("query")
    @classmethod
    def clean_query(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Query cannot be empty or whitespace only.")
        return cleaned


class DiscoveryResponse(BaseModel):
    """Outbound prospect discovery response matching exact API specification."""

    success: bool = Field(
        default=True,
        description="Indicates whether the discovery pipeline completed successfully.",
    )
    query: str = Field(
        ...,
        description="Echo of the original query.",
    )
    total_prospects: int = Field(
        ...,
        description="Total count of verified prospects discovered.",
    )
    prospects: list[Prospect] = Field(
        default_factory=list,
        description="Array of verified prospect objects. Empty if none found.",
    )


# --- Internal Intermediate Schemas ---


class LocationIntent(BaseModel):
    """Structured location components parsed from query."""

    city: str | None = None
    state: str | None = None
    country: str | None = None
    raw: str | None = None

    def display(self) -> str:
        """Format location as city, state/country string."""
        parts = [p for p in (self.city, self.state, self.country) if p]
        if parts:
            return ", ".join(parts)
        return self.raw or ""


class QueryIntent(BaseModel):
    raw_query: str | None = Field(
        default=None,
        description="The original unparsed query string.",
    )
    interest: list[str] = Field(
        default_factory=list,
        description="Target domains, technologies, skills, or industries.",
    )
    audience: list[str] = Field(
        default_factory=list,
        description="Target professional titles, roles, or organization types.",
    )
    location: LocationIntent = Field(
        default_factory=LocationIntent,
        description="Geographic scope.",
    )
    target_type: Literal["individual", "company", "creator", "any"] = Field(
        default="any",
        description="Inferred entity type.",
    )
    target_platforms: list[SocialPlatform] = Field(
        default_factory=list,
        description="Platforms explicitly or implicitly prioritized.",
    )
    suggested_queries: list[str] = Field(
        default_factory=list,
        description="4-6 targeted, grouped queries for Tavily search.",
    )


class TavilySearchResult(BaseModel):
    """Single Tavily web search result item."""

    title: str
    url: str
    content: str
    raw_content: str | None = None
    score: float | None = None


class CandidateProfile(BaseModel):
    """Intermediate extracted profile before deduplication and relevance checks."""

    name: str
    platform: SocialPlatform
    profile_url: str
    title: str | None = None
    snippet: str | None = None
    location: str | None = None
    handle: str | None = None
    domain: str | None = None
    company: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    whatsapp_links: list[str] = Field(default_factory=list)
    additional_links: list[SocialLink] = Field(default_factory=list)
    raw_content: str | None = None
    confidence_score: float = 0.0
