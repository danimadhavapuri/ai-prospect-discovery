"""Google / Official Web Entity discovery adapter.

Handles discovery of verified official websites, portfolio domains, and Google entity
profiles from search results.
"""

import re
import urllib.parse

from app.platforms.base import BasePlatform
from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult
from app.utils.normalizers import clean_entity_name
from app.utils.validators import clean_url, is_search_engine_result_url, validate_email, validate_phone

# Non-Google social domains handled by other specialized platform adapters
OTHER_SOCIAL_DOMAINS = {
    "linkedin.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "instagram.com",
    "facebook.com",
    "fb.com",
    "threads.net",
    "wa.me",
    "whatsapp.com",
}


class GooglePlatform(BasePlatform):
    """Adapter for official web domains and Google business/entity profile discovery."""

    @property
    def name(self) -> SocialPlatform:
        return "Google"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        if is_search_engine_result_url(url):
            return False

        clean = clean_url(url)
        if not clean:
            return False

        try:
            parsed = urllib.parse.urlsplit(clean)
            host = (parsed.hostname or "").lower()
            if any(soc in host for soc in OTHER_SOCIAL_DOMAINS):
                return False
            return bool(host and "." in host)
        except Exception:
            return False

    def extract_candidates(
        self, results: list[TavilySearchResult], intent: QueryIntent
    ) -> list[CandidateProfile]:
        candidates: list[CandidateProfile] = []

        for item in results:
            if not self.matches_url(item.url):
                continue

            cleaned_link = clean_url(item.url)
            if not cleaned_link:
                continue

            name = self._parse_name(item.title, cleaned_link)
            if not name:
                continue

            parsed = urllib.parse.urlsplit(cleaned_link)
            domain = parsed.hostname.lower() if parsed.hostname else None

            location = self._extract_location(item.content, intent)
            emails = self._extract_emails(item.content)
            phones = self._extract_phones(item.content)

            candidates.append(
                CandidateProfile(
                    name=name,
                    platform=self.name,
                    profile_url=cleaned_link,
                    snippet=item.content[:500],
                    location=location,
                    domain=domain,
                    emails=emails,
                    phones=phones,
                    raw_content=item.raw_content,
                    confidence_score=0.8,
                )
            )

        return candidates

    def _parse_name(self, raw_title: str, url: str) -> str | None:
        if raw_title:
            cleaned = clean_entity_name(raw_title)
            if cleaned:
                return cleaned

        try:
            host = urllib.parse.urlsplit(url).hostname or ""
            domain_part = host.replace("www.", "").split(".")[0]
            if 2 <= len(domain_part) <= 40 and not domain_part.isdigit():
                return domain_part.capitalize()
        except Exception:
            pass

        return None

    def _extract_location(self, text: str, intent: QueryIntent) -> str | None:
        if not text:
            return intent.location.display() or None

        match = re.search(r"(?:Based in|Located in|Address[:\s]+)([A-Z][a-zA-Z\s,]+)", text)
        if match:
            cand = match.group(1).strip()
            if 2 < len(cand) < 40:
                return cand

        return intent.location.display() or None

    def _extract_emails(self, text: str) -> list[str]:
        if not text:
            return []
        found = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
        valid = []
        for e in found:
            norm = validate_email(e)
            if norm and norm not in valid:
                valid.append(norm)
        return valid

    def _extract_phones(self, text: str) -> list[str]:
        if not text:
            return []
        found = re.findall(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
        valid = []
        for p in found:
            norm = validate_phone(p)
            if norm and norm not in valid:
                valid.append(norm)
        return valid
