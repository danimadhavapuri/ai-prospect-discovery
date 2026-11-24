"""Profile and contact extraction service.

Coordinates platform discovery adapters and extracts verified names, locations,
cross-platform links, public RFC-compliant emails, and WhatsApp contacts.
Applies entity name cleaning and location normalization.
"""

import logging
import re
from typing import Any

from app.platforms import ALL_PLATFORMS
from app.schemas import CandidateProfile, QueryIntent, SocialLink, TavilySearchResult
from app.utils.normalizers import clean_entity_name, normalize_location
from app.utils.validators import (
    clean_url,
    identify_platform,
    validate_email,
    validate_phone,
    validate_whatsapp,
)

logger = logging.getLogger("prospect_discovery.extractor")


class ProfileExtractor:
    """Extracts candidate prospect profiles and verified cross-platform contact links."""

    def extract_candidates_from_results(
        self, results: list[TavilySearchResult], intent: QueryIntent
    ) -> list[CandidateProfile]:
        """Run all platform adapters over search results to discover candidate profiles."""
        raw_candidates: list[CandidateProfile] = []

        for platform in ALL_PLATFORMS:
            try:
                extracted = platform.safe_extract_candidates(results, intent)
                raw_candidates.extend(extracted)
            except Exception as e:
                logger.error("Error in platform %s extraction: %s", platform.name, e)

        # Clean names, normalize locations, and enrich candidates
        cleaned_candidates: list[CandidateProfile] = []
        query_loc_display = intent.location.display() if intent.location else None

        for cand in raw_candidates:
            # 1. Clean entity name. If it's boilerplate ("Contact", "Home") or raw URL, drop it.
            cleaned_name = clean_entity_name(cand.name)
            if not cleaned_name:
                logger.debug("Dropping candidate with unverified/boilerplate name: '%s'", cand.name)
                continue
            cand.name = cleaned_name

            # 2. Normalize location and fix truncated artifacts
            cand.location = normalize_location(cand.location, query_loc_display, cand.snippet)

            # 3. Enrich candidate with cross-platform links, emails, and WhatsApp
            self._enrich_candidate(cand)
            cleaned_candidates.append(cand)

        return cleaned_candidates

    def _enrich_candidate(self, cand: CandidateProfile) -> None:
        """Scan candidate snippet and content for cross-referenced social URLs, emails, and WhatsApp."""
        text_corpus = f"{cand.snippet or ''} {cand.raw_content or ''}"
        if not text_corpus.strip():
            return

        # 1. Extract and validate emails -> convert to SocialLink(platform="Email", link="mailto:...")
        found_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text_corpus)
        for e in found_emails:
            norm_email = validate_email(e)
            if norm_email and norm_email not in cand.emails:
                cand.emails.append(norm_email)
                cand.additional_links.append(
                    SocialLink(platform="Email", link=norm_email)
                )

        # 2. Extract and validate WhatsApp links (with or without https://)
        wa_urls = re.findall(r"(?:https?://)?(?:wa\.me/|api\.whatsapp\.com/send\?phone=)[^\s\"'<>]+", text_corpus)
        for w in wa_urls:
            norm_wa = validate_whatsapp(w)
            if norm_wa and norm_wa not in cand.whatsapp_links:
                cand.whatsapp_links.append(norm_wa)
                cand.additional_links.append(
                    SocialLink(platform="WhatsApp", link=norm_wa)
                )

        # 3. Extract other social URLs mentioned in bio/snippet
        other_urls = re.findall(r"https?://[^\s\"'<>,]+", text_corpus)
        for raw_u in other_urls:
            clean_u = clean_url(raw_u)
            if not clean_u:
                continue

            plat = identify_platform(clean_u)
            if plat and plat != cand.platform and plat not in ("Google", "Email"):
                # Avoid adding self-link
                if clean_u != cand.profile_url:
                    cand.additional_links.append(
                        SocialLink(platform=plat, link=clean_u)
                    )


# Singleton instance
profile_extractor = ProfileExtractor()
