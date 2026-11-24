"""Prospect discovery pipeline orchestrator.

Asynchronously coordinates:
1. Query understanding (Gemini / NLP rule-based fallback).
2. Multi-platform search execution via Tavily Search API with TTL caching.
3. Platform-specific candidate profile and public contact extraction.
4. Intelligent deduplication and entity resolution.
5. Relevance and zero-fabrication quality filtering.
6. Schema-compliant response synthesis.
"""

import logging
from typing import Any

from app.schemas import DiscoveryResponse, Prospect, QueryIntent
from app.services.deduplication_service import deduplication_service
from app.services.profile_extractor import profile_extractor
from app.services.query_service import query_service
from app.services.relevance_service import relevance_service
from app.services.search_service import search_service

logger = logging.getLogger("prospect_discovery.orchestrator")


class ProspectService:
    """Full asynchronous orchestrator for the prospect discovery pipeline."""

    async def discover_prospects(self, query: str) -> DiscoveryResponse:
        """Execute the end-to-end prospect discovery pipeline.

        Guarantees:
        - ZERO FABRICATION: Never invents names, emails, phone numbers, or social links.
        - Graceful handling: Returns empty list if no verified prospects are found.
        - Strict response schema compliance.
        """
        clean_query = query.strip()
        logger.info("Initiating prospect discovery for query: '%s'", clean_query)

        # Step 1: Parse natural language intent into structured query groups
        intent = await query_service.parse_query(clean_query)
        logger.debug(
            "Parsed query intent: interest=%s, audience=%s, location=%s, queries=%d",
            intent.interest,
            intent.audience,
            intent.location.display(),
            len(intent.suggested_queries),
        )

        # Step 2: Concurrently query Tavily Search API
        search_results = await search_service.search_queries_concurrent(
            intent.suggested_queries
        )
        logger.info(
            "Retrieved %d unique search results across platforms for query '%s'",
            len(search_results),
            clean_query,
        )

        if not search_results:
            logger.info("No search results returned. Returning zero-prospect response.")
            return DiscoveryResponse(
                success=True,
                query=clean_query,
                total_prospects=0,
                prospects=[],
            )

        # Step 3: Extract candidate profiles and contacts across all platform adapters
        candidates = profile_extractor.extract_candidates_from_results(
            search_results, intent
        )
        logger.info("Extracted %d raw candidate profiles from search results", len(candidates))

        if not candidates:
            return DiscoveryResponse(
                success=True,
                query=clean_query,
                total_prospects=0,
                prospects=[],
            )

        # Step 4: Consolidate duplicate profiles of same entity & disambiguate distinct same-name people
        consolidated = deduplication_service.deduplicate(candidates)
        logger.info("Consolidated into %d distinct candidate entities", len(consolidated))

        # Step 5: Filter for relevance, format validity, and zero-fabrication quality
        final_prospects = relevance_service.filter_and_rank_prospects(
            consolidated, intent
        )
        logger.info("Filtered to %d verified high-quality prospects", len(final_prospects))

        # Step 6: Return strictly schema-compliant response
        return DiscoveryResponse(
            success=True,
            query=clean_query,
            total_prospects=len(final_prospects),
            prospects=final_prospects,
        )


# Singleton instance
prospect_service = ProspectService()
