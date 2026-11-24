"""Relevance evaluation and quality verification service.

Evaluates prospect candidates against the user's intended interest, audience,
and location scope, discarding low-evidence matches, listicles, blog posts,
directories, off-topic mismatches, and fabricated artifacts.
"""

import logging
import re

from app.schemas import Prospect, QueryIntent
from app.utils.normalizers import clean_entity_name, normalize_location
from app.utils.validators import is_search_engine_result_url

logger = logging.getLogger("prospect_discovery.relevance")

# Common junk titles, articles, listicles, directories, and blog posts to discard
LISTICLE_AND_ARTICLE_PATTERNS = [
    # Listicles: "Top 10...", "Best 20...", "The 29 Coolest...", "10 Leading..."
    r"^(?:the\s+)?(?:\d+\s+)?(?:best|top|coolest|leading|popular|most|greatest|ultimate|key|essential)\s+",
    r"\b\d+\s+(?:best|top|coolest|leading|popular|greatest)\b",
    # Directories and email lists: "Marketing Agency Email List", "Restaurants Email List UAE"
    r"\b(?:email\s+list|database|leads\s+list|mailing\s+list|contact\s+list|agency\s+list|companies\s+list)\b",
    r"\b(?:directory\s+of|business\s+directory|company\s+directory|yellow\s+pages)\b",
    # Informational guides & blog posts: "What the Founder's Email Address Says...", "How to Start a Restaurant..."
    r"^what\s+(?:the\s+)?[a-z'\s]+\s+(?:says|means|does|is|are)\b",
    r"^how\s+(?:to\s+)?[a-z'\s]+\b",
    # Costs, licensing, and reports: "Restaurant License Cost in Dubai", "Startup Costs..."
    r"\b(?:license\s+cost|cost\s+of|pricing\s+guide|how\s+much\s+does|step\s+by\s+step|guide\s+to\s+start)\b",
    r"\b(?:market\s+research|industry\s+report|market\s+size|market\s+share|statistics\s+20\d\d)\b",
    r"\b(?:everything\s+you\s+need\s+to\s+know|complete\s+guide|comprehensive\s+guide)\b",
    # Commercial spam
    r"\b(?:free\s+trial|coupon\s+code|discount\s+code|promo\s+code)\b",
    # Generic portal and navigation terms
    r"\b(?:log\s*in|login|sign\s*in|signin|sign\s*up|signup)\b",
    r"\b(?:privacy\s+policy|terms\s+of\s+service|terms\s+and\s+conditions|cookie\s+policy)\b",
    r"\b(?:search\s+results|all\s+categories|browse\s+by)\b",
    r"^(?:home|front\s+page|welcome|about\s+us|contact\s+us)$",
]

# Major regional clusters for cross-location conflict detection
REGIONAL_CLUSTERS = {
    "dubai": ["dubai", "uae", "united arab emirates", "sharjah", "abu dhabi"],
    "ahmedabad": ["ahmedabad", "gujarat", "india"],
    "london": ["london", "uk", "united kingdom", "england", "great britain"],
    "new york": ["new york", "ny", "nyc", "manhattan", "brooklyn"],
    "washington": ["washington", "dc", "district of columbia"],
}

DISTANT_COUNTRIES = [
    "australia",
    "canada",
    "germany",
    "france",
    "brazil",
    "japan",
    "russia",
    "china",
    "singapore",
    "philippines",
]


class RelevanceService:
    """Filters and scores prospects against query intent and quality thresholds."""

    def filter_and_rank_prospects(
        self, prospects: list[Prospect], intent: QueryIntent
    ) -> list[Prospect]:
        """Filter out invalid, fabricated, or irrelevant prospects and return verified prospects."""
        verified_prospects: list[Prospect] = []

        for p in prospects:
            # Step 1: Clean entity name using centralized normalizer
            clean_name = clean_entity_name(p.name)
            if not clean_name:
                continue
            p.name = clean_name

            # Step 2: Normalize location
            query_loc_display = intent.location.display() if intent.location else None
            p.location = normalize_location(p.location, query_loc_display)

            # Step 3: Validate prospect criteria
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

        name_lower = clean_name.lower()

        # Reject listicle, article, directory, or blog post patterns
        for pattern in LISTICLE_AND_ARTICLE_PATTERNS:
            if re.search(pattern, name_lower):
                logger.debug("Rejecting listicle/article title: '%s'", clean_name)
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

        # Reject off-topic matches (e.g. music band for sports, real estate for restaurant)
        if self._is_off_topic(p, intent):
            logger.debug("Rejecting off-topic match: '%s'", p.name)
            return False

        # Reject off-location matches where prospect location explicitly conflicts with query
        if self._is_off_location(p, intent):
            logger.debug("Rejecting off-location match: '%s' in '%s'", p.name, p.location)
            return False

        return True

    def _is_off_topic(self, p: Prospect, intent: QueryIntent) -> bool:
        """Detect obvious entity topic mismatches against query intent."""
        name_low = p.name.lower()
        raw_q = getattr(intent, "raw_query", None) or ""
        interests = intent.interest if isinstance(intent.interest, list) else [intent.interest or ""]
        audiences = intent.audience if isinstance(intent.audience, list) else [intent.audience or ""]
        query_context = f"{raw_q} {' '.join(interests)} {' '.join(audiences)}".lower()

        # 1. American Football (the rock/emo band) vs Football lovers
        if "football" in query_context:
            if name_low in ("american football", "american football band", "americanfootballmusic"):
                return True

        # 2. Real estate agencies/brokers when searching for restaurant owners
        if "restaurant" in query_context and "real estate" not in query_context:
            if any(term in name_low for term in ("real estate", "realty", "properties", "property broker", "brokerage")):
                return True

        return False

    def _is_off_location(self, p: Prospect, intent: QueryIntent) -> bool:
        """Check if candidate is explicitly located in a conflicting, distant region not in query."""
        if not p.location or not intent.location:
            return False

        query_loc = intent.location.display().lower()
        prospect_loc = p.location.lower()

        # Find which major cluster the query targets
        target_cluster_key = None
        for key in REGIONAL_CLUSTERS:
            if key in query_loc:
                target_cluster_key = key
                break

        if not target_cluster_key:
            return False

        allowed_terms = REGIONAL_CLUSTERS[target_cluster_key]
        if any(term in prospect_loc for term in allowed_terms):
            return False  # Matches target cluster!

        # Check for conflict with other known major clusters
        for other_key, other_terms in REGIONAL_CLUSTERS.items():
            if other_key != target_cluster_key:
                if any(term in prospect_loc for term in other_terms):
                    return True  # Conflicting major region!

        # Check for distant countries when query targets a local city
        for country in DISTANT_COUNTRIES:
            if country in prospect_loc and country not in query_loc:
                return True

        return False


# Singleton instance
relevance_service = RelevanceService()
