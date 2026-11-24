"""Facebook discovery adapter.

Handles discovery of verified public Facebook pages and profiles (facebook.com/<handle>)
from search results.
"""

import re
import urllib.parse

from app.platforms.base import BasePlatform
from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult
from app.utils.validators import clean_url, validate_email, validate_phone

EXCLUDED_FACEBOOK_PATHS = (
    "/login",
    "/recover",
    "/sharer",
    "/share",
    "/policies",
    "/help",
    "/marketplace",
    "/groups",
    "/events",
    "/watch",
    "/gaming",
    "/ads",
    "/privacy",
    "/terms",
)


class FacebookPlatform(BasePlatform):
    """Adapter for Facebook page and profile discovery."""

    @property
    def name(self) -> SocialPlatform:
        return "Facebook"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        clean = clean_url(url)
        if not clean:
            return False
        parsed = urllib.parse.urlsplit(clean)
        host = (parsed.hostname or "").lower()
        if host not in ("facebook.com", "www.facebook.com", "fb.com", "web.facebook.com"):
            return False

        path = parsed.path.lower()
        if any(path.startswith(exc) for exc in EXCLUDED_FACEBOOK_PATHS):
            return False

        segments = [s for s in parsed.path.strip("/").split("/") if s]
        return len(segments) >= 1

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

            name = self._parse_name(item.title)
            if not name:
                continue

            parsed = urllib.parse.urlsplit(cleaned_link)
            segments = [s for s in parsed.path.strip("/").split("/") if s]
            handle = segments[0] if segments else None

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
                    handle=handle,
                    emails=emails,
                    phones=phones,
                    raw_content=item.raw_content,
                    confidence_score=0.8,
                )
            )

        return candidates

    def _parse_name(self, raw_title: str) -> str | None:
        if not raw_title:
            return None

        cleaned = re.sub(r"\s*[•\-|]\s*(?:Home\s*\|\s*)?Facebook.*$", "", raw_title, flags=re.IGNORECASE).strip()
        if len(cleaned) < 2 or "facebook" in cleaned.lower():
            return None

        return cleaned

    def _extract_location(self, text: str, intent: QueryIntent) -> str | None:
        if not text:
            return intent.location.display() or None

        match = re.search(r"(?:Located in|Based in|Address:)\s+([A-Z][a-zA-Z\s,]+)", text)
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
