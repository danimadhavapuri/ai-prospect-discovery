"""Dynamic natural language query parsing service.

Extracts structured intent (interest, audience, location, target entity type,
preferred platforms) and crafts 4-6 targeted, grouped Tavily search queries.
Uses Gemini LLM when available with a deterministic NLP rule-based fallback.
Zero hardcoded queries. Fully dynamic.
"""

import logging
import re
from typing import Any

from app.schemas import LocationIntent, QueryIntent, SocialPlatform
from app.services.llm_service import llm_service
from app.utils.cache import query_intent_cache

logger = logging.getLogger("prospect_discovery.query_service")

# Common location indicators in queries
LOCATION_PREPOSITIONS = ("in", "at", "around", "near", "based in", "located in", "from")

# Platform keywords mapped to canonical platform names
PLATFORM_KEYWORDS: dict[str, SocialPlatform] = {
    "linkedin": "LinkedIn",
    "twitter": "X",
    "x.com": "X",
    "x": "X",
    "youtube": "YouTube",
    "yt": "YouTube",
    "instagram": "Instagram",
    "ig": "Instagram",
    "insta": "Instagram",
    "whatsapp": "WhatsApp",
    "wa": "WhatsApp",
    "facebook": "Facebook",
    "fb": "Facebook",
    "threads": "Threads",
    "email": "Email",
    "mail": "Email",
    "google": "Google",
    "website": "Google",
}

ROLE_KEYWORDS = {
    "founder", "founders", "co-founder", "co-founders", "ceo", "ceos", "cto", "ctos",
    "cfo", "coo", "vp", "director", "manager", "head", "lead", "engineer", "engineers",
    "developer", "developers", "designer", "designers", "creator", "creators",
    "consultant", "consultants", "advisor", "advisors", "coach", "coaches",
    "instructor", "instructors", "freelancer", "freelancers", "architect", "architects",
    "investor", "investors", "analyst", "analysts", "doctor", "lawyer", "agency", "agencies",
    "expert", "specialist",
}


class QueryService:
    """Natural language query parsing and search query generation engine."""

    async def parse_query(self, raw_query: str) -> QueryIntent:
        """Parse natural language query into structured QueryIntent with cache check."""
        cache_key = f"query_intent:{raw_query.strip().lower()}"
        cached = await query_intent_cache.get(cache_key)
        if cached:
            logger.debug("Cache hit for query intent: %s", raw_query)
            return QueryIntent.model_validate(cached)

        intent: QueryIntent | None = None

        # Attempt Gemini LLM structured parsing
        if llm_service.is_available:
            try:
                intent = await self._parse_with_gemini(raw_query)
            except Exception as e:
                logger.warning("Gemini query parsing failed, falling back to rule-based: %s", e)

        # Fallback to deterministic NLP rules if LLM unavailable or failed
        if not intent:
            intent = self._parse_with_rules(raw_query)

        # Ensure raw query is preserved
        intent.raw_query = raw_query.strip()

        # Ensure suggested queries are always generated and bounded
        if not intent.suggested_queries:
            intent.suggested_queries = self._generate_search_queries(intent)

        # Cache the parsed intent
        await query_intent_cache.set(cache_key, intent.model_dump())
        return intent

    async def _parse_with_gemini(self, query: str) -> QueryIntent | None:
        """Use Google Gemini to extract fine-grained intent and search query groups."""
        system_instruction = (
            "You are an expert search query analyzer for prospect discovery. "
            "Analyze the user's natural language search request and extract structured intent. "
            "Return JSON matching this exact structure: "
            "{\n"
            '  "interest": ["domain", "skills", "niche"],\n'
            '  "audience": ["target role, title, or organization"],\n'
            '  "location": {"city": "...", "state": "...", "country": "...", "raw": "..."},\n'
            '  "target_type": "individual"|"company"|"creator"|"any",\n'
            '  "target_platforms": ["LinkedIn", "X", "YouTube", "Instagram", "WhatsApp", "Facebook", "Email", "Threads", "Google"],\n'
            '  "suggested_queries": ["query 1", "query 2", "query 3", "query 4", "query 5"]\n'
            "}\n"
            "Generate 4 to 6 grouped search queries optimized for Tavily using site: operators for "
            "major platforms (site:linkedin.com/in, site:x.com, site:instagram.com, site:youtube.com, site:threads.net, site:wa.me)."
        )

        prompt = f"Analyze this prospect discovery search query: '{query}'"
        result_json = await llm_service.generate_structured_json(
            prompt=prompt,
            system_instruction=system_instruction,
        )

        if not result_json:
            return None

        try:
            loc_data = result_json.get("location") or {}
            loc_intent = LocationIntent(
                city=loc_data.get("city"),
                state=loc_data.get("state"),
                country=loc_data.get("country"),
                raw=loc_data.get("raw"),
            )

            valid_platforms: list[SocialPlatform] = []
            for p in result_json.get("target_platforms", []):
                if p in ("Google", "LinkedIn", "X", "YouTube", "Instagram", "WhatsApp", "Facebook", "Email", "Threads"):
                    valid_platforms.append(p)

            queries = [q for q in result_json.get("suggested_queries", []) if isinstance(q, str) and q.strip()]
            # Keep between 4 and 6 queries
            queries = queries[:6]

            return QueryIntent(
                interest=result_json.get("interest", []),
                audience=result_json.get("audience", []),
                location=loc_intent,
                target_type=result_json.get("target_type", "any"),
                target_platforms=valid_platforms,
                suggested_queries=queries,
            )
        except Exception as e:
            logger.warning("Error deserializing Gemini query response: %s", e)
            return None

    def _parse_with_rules(self, query: str) -> QueryIntent:
        """Deterministic rule-based NLP parser for test environments and offline fallback."""
        query_lower = query.lower()
        tokens = re.findall(r"\b[\w.-]+\b", query)

        # Detect target platforms
        platforms: list[SocialPlatform] = []
        for kw, plat in PLATFORM_KEYWORDS.items():
            if re.search(r"\b" + re.escape(kw) + r"\b", query_lower):
                if plat not in platforms:
                    platforms.append(plat)

        # Extract location
        location_raw: str | None = None
        for prep in LOCATION_PREPOSITIONS:
            pattern = r"\b" + re.escape(prep) + r"\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*(?:,\s*[A-Z][a-zA-Z]+)*)"
            match = re.search(pattern, query)
            if match:
                location_raw = match.group(1).strip()
                break

        city, state, country = None, None, None
        if location_raw:
            parts = [p.strip() for p in location_raw.split(",")]
            if len(parts) >= 2:
                city = parts[0]
                state = parts[1]
            else:
                city = parts[0]

        # Extract audience roles
        audience: list[str] = []
        interest: list[str] = []

        for token in tokens:
            t_lower = token.lower()
            if t_lower in ROLE_KEYWORDS:
                audience.append(token)
            elif t_lower not in PLATFORM_KEYWORDS and t_lower not in {
                "find", "search", "get", "discover", "look", "for", "with", "and", "or", "in", "at", "the", "a", "an", "based", "near"
            }:
                # Avoid adding location words to interest
                if location_raw and token.lower() in location_raw.lower():
                    continue
                interest.append(token)

        target_type = "individual" if audience else "any"

        intent = QueryIntent(
            interest=interest,
            audience=audience,
            location=LocationIntent(city=city, state=state, country=country, raw=location_raw),
            target_type=target_type,
            target_platforms=platforms,
        )

        intent.suggested_queries = self._generate_search_queries(intent)
        return intent

    def _generate_search_queries(self, intent: QueryIntent) -> list[str]:
        """Generate 4 to 6 grouped search queries for multi-platform Tavily discovery."""
        interest_str = " ".join(intent.interest[:3]) if intent.interest else ""
        audience_str = " ".join(intent.audience[:2]) if intent.audience else ""
        location_str = intent.location.display()

        core_terms = []
        if interest_str:
            core_terms.append(f'"{interest_str}"')
        if audience_str:
            core_terms.append(f'"{audience_str}"')
        if location_str:
            core_terms.append(f'"{location_str}"')

        base_str = " ".join(core_terms) if core_terms else "prospects"

        # 4-6 Grouped queries across the 9 platforms
        queries = [
            # Group 1: LinkedIn Professional Profiles & Organizations
            f'site:linkedin.com/in OR site:linkedin.com/company {base_str}',
            # Group 2: X (Twitter) & Threads Profiles
            f'(site:x.com OR site:threads.net) {base_str}',
            # Group 3: YouTube Channels & Instagram Profiles
            f'(site:youtube.com/@ OR site:instagram.com) {base_str}',
            # Group 4: WhatsApp Contacts & Direct Communications
            f'(site:wa.me OR "api.whatsapp.com/send") {base_str}',
            # Group 5: Official Websites, Portfolios, and Contact Listings
            f'{base_str} contact email official website',
        ]

        # If user explicitly asked for Facebook, add a Facebook-targeted query
        if "Facebook" in intent.target_platforms:
            queries.append(f'site:facebook.com {base_str}')

        return queries[:6]


# Singleton instance
query_service = QueryService()
