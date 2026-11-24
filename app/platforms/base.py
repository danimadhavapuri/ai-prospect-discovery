"""Base platform discovery adapter.

Defines the interface for platform-specific discovery, URL matching,
and isolated candidate extraction.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any

from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult

logger = logging.getLogger("prospect_discovery.platform")


class BasePlatform(ABC):
    """Abstract base class for platform-specific discovery adapters."""

    @property
    @abstractmethod
    def name(self) -> SocialPlatform:
        """Canonical name of platform matching exact API specification."""
        pass

    @abstractmethod
    def matches_url(self, url: str) -> bool:
        """Return True if URL is a recognized entity/profile link for this platform."""
        pass

    @abstractmethod
    def extract_candidates(
        self, results: list[TavilySearchResult], intent: QueryIntent
    ) -> list[CandidateProfile]:
        """Extract candidate profiles from search results with strict error isolation."""
        pass

    def safe_extract_candidates(
        self, results: list[TavilySearchResult], intent: QueryIntent
    ) -> list[CandidateProfile]:
        """Wrapper ensuring platform extraction never crashes the orchestrator."""
        try:
            return self.extract_candidates(results, intent)
        except Exception as e:
            logger.error(
                "Error extracting candidates in platform %s: %s",
                self.name,
                e.__class__.__name__,
            )
            return []
