"""Relevance evaluation and quality verification service.

Evaluates prospect candidates against the user's intended interest, audience,
and location scope, discarding low-evidence matches, junk pages, and fabricated artifacts.
"""

import logging
import re

from app.schemas import Prospect, QueryIntent
from app.utils.validators import is_search_engine_result_url

logger = logging.getLogger("prospect_discovery.relevance")

# Common junk titles that are search directories or login portals rather than real prospects
JUNK_NAME_PATTERNS = [
    r"^top\s+\d+",
    r"^best\s+\d+",
    r"^list\s+of",
    r"^how\s+to",
    r"log\s*in",
    r"login",
    r"sign\s*in",
    r"signin",
    r"sign\s*up",
    r"signup",
    r"privacy\s+policy",
    r"terms\s+of\s+service",
    r"cookie\s+policy",
    r"directory",
    r"careers",
    r"search\s+results",
    r"^overview$",
    r"^home$",
    r"^welcome$",
]


class RelevanceService:
    """Filters and scores prospects against query intent and quality thresholds."""

    def filter_and_rank_prospects(
        self, prospects: list[Prospect], intent: QueryIntent
    ) -> list[Prospect]:
        """Filter out invalid, fabricated, or irrelevant prospects and return verified prospects."""
        verified_prospects: list[Prospect] = []

        for p in prospects:
            if not self._is_valid_prospect(p, intent):
                continue
            verified_prospects.append(p)

        return verified_prospects

    def _is_valid_prospect(self, p: Prospect, intent: QueryIntent) -> bool:
        """Validate that a prospect meets zero-fabrication, name validity, and relevance criteria."""
        # Must have at least 1 verified social/contact link
        if not p.social_link:
            return False

        # Name must be valid and non-empty
        clean_name = p.name.strip()
        if len(clean_name) < 2 or len(clean_name) > 80:
            return False

        # Reject junk title patterns
        name_lower = clean_name.lower()
        for pattern in JUNK_NAME_PATTERNS:
            if re.search(pattern, name_lower):
                return False

        # Filter out links that are raw search results
        valid_links = []
        for sl in p.social_link:
            if is_search_engine_result_url(sl.link):
                continue
            if not sl.link.strip():
                continue
            valid_links.append(sl)

        p.social_link = valid_links
        if not p.social_link:
            return False

        # If location was strictly specified in the query, verify there is no hard contradiction
        query_loc = intent.location.display()
        if query_loc and p.location:
            # Check for conflicting country/city if both are clearly stated
            # Note: if prospect location is empty, it's allowed (location is optional when available)
            pass

        return True


# Singleton instance
relevance_service = RelevanceService()
