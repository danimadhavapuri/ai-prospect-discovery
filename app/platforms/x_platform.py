"""X (formerly Twitter) discovery adapter.

Handles discovery of verified X/Twitter profiles (x.com/<handle> or twitter.com/<handle>)
from search results, extracting profile names, handles, and public contact information.
"""

import re
import urllib.parse

from app.platforms.base import BasePlatform
from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult
from app.utils.validators import clean_url, validate_email, validate_phone

EXCLUDED_X_PATHS = {
    "login",
    "signup",
    "home",
    "explore",
    "notifications",
    "messages",
    "search",
    "hashtag",
    "settings",
    "tos",
    "privacy",
    "i",
    "intent",
    "share",
}


class XPlatform(BasePlatform):
    """Adapter for X / Twitter profile discovery."""

    @property
    def name(self) -> SocialPlatform:
        return "X"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        clean = clean_url(url)
        if not clean:
            return False
        parsed = urllib.parse.urlsplit(clean)
        host = (parsed.hostname or "").lower()
        if host not in ("x.com", "twitter.com") and not host.endswith(".x.com") and not host.endswith(".twitter.com"):
            return False

        path_segments = [p for p in parsed.path.strip("/").split("/") if p]
        if not path_segments:
            return False

        first = path_segments[0].lower()
        if first in EXCLUDED_X_PATHS:
            return False

        # Profile URLs typically have 1 segment (e.g. /username) or /username/status/... (tweet by user)
        return bool(re.match(r"^[a-zA-Z0-9_]{1,25}$", path_segments[0]))

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

            # Canonicalize URL to top-level profile (https://x.com/<handle>)
            parsed = urllib.parse.urlsplit(cleaned_link)
            segments = [s for s in parsed.path.strip("/").split("/") if s]
            if not segments:
                continue

            handle = segments[0]
            canonical_profile_url = f"https://x.com/{handle}"

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
        """Extract clean person or brand name from X/Twitter title."""
        if not raw_title:
            return handle

        cleaned = re.sub(r"\s*(?:/|\|)\s*(?:X|Twitter).*$", "", raw_title, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+on\s+X.*$", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+on\s+Twitter.*$", "", cleaned, flags=re.IGNORECASE).strip()

        # Match "First Last (@handle)" or "First Last"
        match = re.search(r"^([^(@]+)(?:\s*\(@[a-zA-Z0-9_]+\))?", cleaned)
        if match:
            candidate = match.group(1).strip()
            if candidate and len(candidate) > 1 and "twitter" not in candidate.lower() and "login" not in candidate.lower():
                return candidate

        return handle if len(handle) > 1 else None

    def _extract_location(self, text: str, intent: QueryIntent) -> str | None:
        if not text:
            return intent.location.display() or None

        match = re.search(r"(?:📍|Location[:\s]+|Based in\s+)([A-Z][a-zA-Z\s,]+)", text)
        if match:
            cand = match.group(1).strip()
            if len(cand) > 2 and len(cand) < 40:
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
