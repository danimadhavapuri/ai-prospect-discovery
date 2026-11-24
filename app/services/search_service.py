"""Async Tavily Search API client with TTL caching and concurrency limits.

Executes lean, deduplicated queries against https://api.tavily.com/search
with exponential backoff, rate limiting, and zero-fabrication guarantees.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.schemas import TavilySearchResult
from app.utils.cache import search_response_cache

logger = logging.getLogger("prospect_discovery.search_service")

TAVILY_API_URL = "https://api.tavily.com/search"


class SearchService:
    """Async Tavily search manager with TTL caching and request pooling."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._semaphore: asyncio.Semaphore | None = None

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Lazily initialize asyncio Semaphore within the active event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.settings.max_search_concurrency)
        return self._semaphore

    @property
    def is_available(self) -> bool:
        """Check if Tavily API key is configured."""
        return self.settings.has_tavily_key

    async def search_single(self, query: str, max_results: int = 10) -> list[TavilySearchResult]:
        """Execute a single search query against Tavily with TTL cache and retries."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        # Check in-memory TTL cache first to conserve Tavily credits
        cache_key = f"tavily:{cleaned_query.lower()}:{max_results}"
        cached = await search_response_cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for Tavily search: %s", cleaned_query)
            return [TavilySearchResult.model_validate(item) for item in cached]

        if not self.is_available:
            logger.warning("Tavily API key is missing. Graceful empty fallback (Zero Fabrication).")
            return []

        payload = {
            "api_key": self.settings.tavily_api_key,
            "query": cleaned_query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }

        results: list[TavilySearchResult] = []
        retries = 2

        async with self.semaphore:
            for attempt in range(retries + 1):
                try:
                    async with httpx.AsyncClient(
                        timeout=self.settings.search_timeout_seconds,
                        headers={"Content-Type": "application/json"},
                    ) as client:
                        response = await client.post(TAVILY_API_URL, json=payload)

                        if response.status_code == 200:
                            data = response.json()
                            raw_results = data.get("results", [])
                            for item in raw_results:
                                if isinstance(item, dict) and item.get("url"):
                                    results.append(
                                        TavilySearchResult(
                                            title=item.get("title", "").strip(),
                                            url=item.get("url", "").strip(),
                                            content=item.get("content", "").strip(),
                                            raw_content=item.get("raw_content"),
                                            score=item.get("score"),
                                        )
                                    )
                            # Cache the results on success
                            await search_response_cache.set(
                                cache_key,
                                [r.model_dump() for r in results],
                            )
                            return results

                        elif response.status_code in (429, 500, 502, 503, 504):
                            logger.warning(
                                "Tavily API returned status %d on attempt %d/%d: %s",
                                response.status_code,
                                attempt + 1,
                                retries + 1,
                                response.text[:200],
                            )
                            if attempt < retries:
                                await asyncio.sleep(2**attempt)
                        else:
                            logger.error(
                                "Tavily API error %d: %s",
                                response.status_code,
                                response.text[:200],
                            )
                            break
                except (httpx.TimeoutException, TimeoutError) as e:
                    logger.warning(
                        "Tavily search timeout on attempt %d/%d for '%s': %s",
                        attempt + 1,
                        retries + 1,
                        cleaned_query,
                        e,
                    )
                    if attempt < retries:
                        await asyncio.sleep(2**attempt)
                except Exception as e:
                    logger.error(
                        "Unexpected error during Tavily search on attempt %d/%d: %s",
                        attempt + 1,
                        retries + 1,
                        e.__class__.__name__,
                    )
                    break

        return results

    async def search_queries_concurrent(
        self, queries: list[str], max_results_per_query: int = 10
    ) -> list[TavilySearchResult]:
        """Execute multiple search queries concurrently with deduplication and bounded concurrency."""
        # Deduplicate incoming queries preserving order
        unique_queries: list[str] = []
        seen = set()
        for q in queries:
            norm = q.strip().lower()
            if norm and norm not in seen:
                seen.add(norm)
                unique_queries.append(q.strip())

        if not unique_queries:
            return []

        # Enforce max queries per request limit to prevent credit exhaustion
        capped_queries = unique_queries[: self.settings.max_tavily_queries_per_request]

        tasks = [
            self.search_single(query, max_results=max_results_per_query)
            for query in capped_queries
        ]

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[TavilySearchResult] = []
        seen_urls = set()

        for res in batch_results:
            if isinstance(res, list):
                for item in res:
                    norm_url = item.url.strip().lower()
                    if norm_url and norm_url not in seen_urls:
                        seen_urls.add(norm_url)
                        all_results.append(item)
            elif isinstance(res, Exception):
                logger.warning("Sub-search task failed: %s", res)

        return all_results


# Singleton instance
search_service = SearchService()
