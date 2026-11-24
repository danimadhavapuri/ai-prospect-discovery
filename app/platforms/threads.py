"""Threads discovery adapter.

Handles discovery of verified Threads profiles (threads.net/@<handle>)
from search results.
"""

import re
import urllib.parse

from app.platforms.base import BasePlatform
from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult
from app.utils.validators import clean_url, validate_email, validate_phone

EXCLUDED_THREADS_PATHS = (
    "/terms",
    "/privacy",
    "/login",
    "/help",
)


class ThreadsPlatform(BasePlatform):
    """Adapter for Threads profile discovery."""

    @property
    def name(self) -> SocialPlatform:
        return "Threads"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        clean = clean_url(url)
        if not clean:
            return False
        parsed = urllib.parse.urlsplit(clean)
        host = (parsed.hostname or "").lower()
        if "threads.net" not in host:
            return False

        path = parsed.path.lower()
        if any(path.startswith(exc) for exc in EXCLUDED_THREADS_PATHS):
            return False

        return path.startswith("/@")

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

            handle = segments[0].lstrip("@")
            canonical_url = f"https://www.threads.net/@{handle}"

            name = self._parse_name(item.title, handle)
            if not name:
                continue

            location = intent.location.display() or None
            emails = self._extract_emails(item.content)
            phones = self._extract_phones(item.content)

            candidates.append(
                CandidateProfile(
                    name=name,
                    platform=self.name,
                    profile_url=canonical_url,
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

        # Clean "on Threads"
        cleaned = re.sub(r"\s+on\s+Threads.*$", "", raw_title, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s*[•\-|]\s*Threads.*$", "", cleaned, flags=re.IGNORECASE).strip()

        # Match "First Last (@handle)"
        match = re.search(r"^([^(@]+)(?:\s*\(@[a-zA-Z0-9_.-]+\))?", cleaned)
        if match:
            candidate = match.group(1).strip()
            if candidate and len(candidate) > 1 and "threads" not in candidate.lower():
                return candidate

        return handle if len(handle) > 1 else None

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
