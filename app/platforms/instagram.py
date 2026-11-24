"""Instagram discovery adapter.

Handles discovery of verified Instagram profiles (instagram.com/<handle>)
from search results, extracting public bios, handles, and contact links.
"""

import re
import urllib.parse

from app.platforms.base import BasePlatform
from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult
from app.utils.validators import clean_url, validate_email, validate_phone

EXCLUDED_INSTAGRAM_PATHS = (
    "/p/",
    "/reel/",
    "/explore/",
    "/stories/",
    "/accounts/",
    "/direct/",
    "/developer/",
    "/legal/",
    "/about/",
    "/terms/",
    "/privacy/",
)


class InstagramPlatform(BasePlatform):
    """Adapter for Instagram profile discovery."""

    @property
    def name(self) -> SocialPlatform:
        return "Instagram"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        clean = clean_url(url)
        if not clean:
            return False
        parsed = urllib.parse.urlsplit(clean)
        host = (parsed.hostname or "").lower()
        if "instagram.com" not in host:
            return False

        path = parsed.path.lower()
        if any(exc in path for exc in EXCLUDED_INSTAGRAM_PATHS):
            return False

        segments = [s for s in parsed.path.strip("/").split("/") if s]
        if not segments:
            return False

        return bool(re.match(r"^[a-zA-Z0-9_.-]{1,30}$", segments[0]))

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

            parsed = urllib.parse.urlsplit(cleaned_link)
            segments = [s for s in parsed.path.strip("/").split("/") if s]
            if not segments:
                continue

            handle = segments[0]
            canonical_profile_url = f"https://www.instagram.com/{handle}"

            name = self._parse_name(item.title, handle)
            if not name:
                continue

            location = self._extract_location(item.content, intent)
            emails = self._extract_emails(item.content)
            phones = self._extract_phones(item.content)

            candidates.append(
                CandidateProfile(
                    name=name,
                    platform=self.name,
                    profile_url=canonical_profile_url,
                    snippet=item.content[:500],
                    location=location,
                    handle=handle,
                    emails=emails,
                    phones=phones,
                    raw_content=item.raw_content,
                    confidence_score=0.85,
                )
            )

        return candidates

    def _parse_name(self, raw_title: str, handle: str) -> str | None:
        if not raw_title:
            return handle

        # Strip "• Instagram photos and videos"
        cleaned = re.sub(r"\s*[•\-|]\s*Instagram.*$", "", raw_title, flags=re.IGNORECASE).strip()

        # Match "First Last (@handle)"
        match = re.search(r"^([^(@]+)(?:\s*\(@[a-zA-Z0-9_.-]+\))?", cleaned)
        if match:
            candidate = match.group(1).strip()
            if candidate and len(candidate) > 1 and "instagram" not in candidate.lower():
                return candidate

        return handle if len(handle) > 1 else None

    def _extract_location(self, text: str, intent: QueryIntent) -> str | None:
        if not text:
            return intent.location.display() or None

        match = re.search(r"(?:📍|Based in\s+|Location[:\s]+)([A-Z][a-zA-Z\s,]+)", text)
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
