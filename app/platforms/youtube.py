"""YouTube discovery adapter.

Handles discovery of verified YouTube creator channels (youtube.com/@<handle>,
youtube.com/channel/..., youtube.com/c/...) from search results.
"""

import re
import urllib.parse

from app.platforms.base import BasePlatform
from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult
from app.utils.validators import clean_url, validate_email, validate_phone

EXCLUDED_YOUTUBE_PATHS = (
    "/watch",
    "/feed",
    "/playlist",
    "/results",
    "/shorts",
    "/gaming",
    "/premium",
    "/music",
    "/t/",
    "/about",
)


class YouTubePlatform(BasePlatform):
    """Adapter for YouTube channel and creator discovery."""

    @property
    def name(self) -> SocialPlatform:
        return "YouTube"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        clean = clean_url(url)
        if not clean:
            return False
        parsed = urllib.parse.urlsplit(clean)
        host = (parsed.hostname or "").lower()
        if host not in ("youtube.com", "www.youtube.com"):
            return False

        path = parsed.path.lower()
        if any(exc in path for exc in EXCLUDED_YOUTUBE_PATHS):
            return False

        return (
            path.startswith("/@")
            or path.startswith("/c/")
            or path.startswith("/channel/")
            or path.startswith("/user/")
        )

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

            handle = self._extract_handle(cleaned_link)
            emails = self._extract_emails(item.content)
            phones = self._extract_phones(item.content)
            location = intent.location.display() or None

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
                    confidence_score=0.85,
                )
            )

        return candidates

    def _parse_name(self, raw_title: str) -> str | None:
        if not raw_title:
            return None

        cleaned = re.sub(r"\s*-\s*YouTube.*$", "", raw_title, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s*\|\s*YouTube.*$", "", cleaned, flags=re.IGNORECASE).strip()

        if len(cleaned) < 2 or "youtube" in cleaned.lower() or "video" in cleaned.lower():
            return None

        return cleaned

    def _extract_handle(self, url: str) -> str | None:
        match = re.search(r"youtube\.com/@([a-zA-Z0-9_.-]+)", url)
        return match.group(1) if match else None

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
