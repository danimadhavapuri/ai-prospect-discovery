"""WhatsApp discovery adapter.

Handles discovery of verified public WhatsApp contact links (wa.me/<digits>
and api.whatsapp.com/send?phone=...) from search results.
"""

import re
import urllib.parse

from app.platforms.base import BasePlatform
from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult
from app.utils.normalizers import clean_entity_name
from app.utils.validators import clean_url, validate_email, validate_whatsapp


class WhatsAppPlatform(BasePlatform):
    """Adapter for WhatsApp direct contact discovery."""

    @property
    def name(self) -> SocialPlatform:
        return "WhatsApp"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        clean = clean_url(url)
        if not clean:
            return False
        parsed = urllib.parse.urlsplit(clean)
        host = (parsed.hostname or "").lower()

        if host in ("wa.me", "api.whatsapp.com"):
            return True

        # Check if URL path has wa.me or api.whatsapp.com
        return "wa.me/" in clean or "api.whatsapp.com" in clean

    def extract_candidates(
        self, results: list[TavilySearchResult], intent: QueryIntent
    ) -> list[CandidateProfile]:
        candidates: list[CandidateProfile] = []

        for item in results:
            wa_link: str | None = None
            if self.matches_url(item.url):
                wa_link = validate_whatsapp(item.url)

            # If not in URL itself, check if wa.me link is explicitly present in snippet
            if not wa_link and item.content:
                wa_match = re.search(r"https?://(?:wa\.me|api\.whatsapp\.com/send\?phone=)[\w+]+", item.content)
                if wa_match:
                    wa_link = validate_whatsapp(wa_match.group(0))

            if not wa_link:
                continue

            name = self._parse_name(item.title)
            if not name:
                continue

            location = intent.location.display() or None

            candidates.append(
                CandidateProfile(
                    name=name,
                    platform=self.name,
                    profile_url=wa_link,
                    snippet=item.content[:500],
                    location=location,
                    whatsapp_links=[wa_link],
                    raw_content=item.raw_content,
                    confidence_score=0.9,
                )
            )

        return candidates

    def _parse_name(self, raw_title: str) -> str | None:
        if not raw_title:
            return None

        # Clean "on WhatsApp", "WhatsApp Group", "Chat on WhatsApp"
        cleaned = re.sub(r"\s*[•\-|]\s*WhatsApp.*$", "", raw_title, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^(?:Chat on|Message|Connect with)\s+", "", cleaned, flags=re.IGNORECASE).strip()

        return clean_entity_name(cleaned)
