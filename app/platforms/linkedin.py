"""LinkedIn discovery adapter.

Handles discovery of verified LinkedIn personal profiles (linkedin.com/in/)
and organization pages (linkedin.com/company/) from search results.
"""

import re
import urllib.parse

from app.platforms.base import BasePlatform
from app.schemas import CandidateProfile, QueryIntent, SocialPlatform, TavilySearchResult
from app.utils.validators import clean_url, validate_email, validate_phone

EXCLUDED_LINKEDIN_PATHS = (
    "/pulse/",
    "/jobs/",
    "/learning/",
    "/help/",
    "/feed/",
    "/login",
    "/signup",
    "/dir/",
    "/legal/",
    "/posts/",
    "/school/",
)


class LinkedInPlatform(BasePlatform):
    """Adapter for LinkedIn prospect discovery."""

    @property
    def name(self) -> SocialPlatform:
        return "LinkedIn"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        clean = clean_url(url)
        if not clean:
            return False
        parsed = urllib.parse.urlsplit(clean)
        host = (parsed.hostname or "").lower()
        if "linkedin.com" not in host:
            return False

        path = parsed.path.lower()
        if any(exc in path for exc in EXCLUDED_LINKEDIN_PATHS):
            return False

        return path.startswith("/in/") or path.startswith("/company/")

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

            name, company, headline = self._parse_title(item.title)
            if not name:
                continue

            # Extract location from snippet or title
            location = self._extract_location(item.snippet_or_content(), intent)

            # Extract public emails
            emails = self._extract_emails(item.content)

            # Extract phone numbers
            phones = self._extract_phones(item.content)

            # Extract handle from path
            handle = self._extract_handle(cleaned_link)

            candidates.append(
                CandidateProfile(
                    name=name,
                    platform=self.name,
                    profile_url=cleaned_link,
                    title=headline,
                    snippet=item.content[:500],
                    location=location,
                    handle=handle,
                    company=company,
                    emails=emails,
                    phones=phones,
                    raw_content=item.raw_content,
                    confidence_score=0.9,
                )
            )

        return candidates

    def _parse_title(self, raw_title: str) -> tuple[str | None, str | None, str | None]:
        """Extract clean name, company, and headline from LinkedIn title string."""
        if not raw_title:
            return None, None, None

        # Clean pipe suffix
        cleaned = re.sub(r"\s*\|\s*LinkedIn.*$", "", raw_title, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s*-\s*LinkedIn.*$", "", cleaned, flags=re.IGNORECASE).strip()

        # Handle "Company Name: Overview"
        if ": Overview" in cleaned:
            comp_name = cleaned.replace(": Overview", "").strip()
            return comp_name, comp_name, "Company"

        # Split on " - "
        parts = [p.strip() for p in cleaned.split(" - ") if p.strip()]
        if not parts:
            return None, None, None

        name_candidate = parts[0]
        # Remove trailing titles like ", Ph.D.", ", MBA"
        name = re.sub(r",\s*(?:Ph\.?D\.?|MBA|MD|Esq\.?|CPA)\b", "", name_candidate, flags=re.IGNORECASE).strip()

        headline = parts[1] if len(parts) > 1 else None
        company = parts[2] if len(parts) > 2 else None

        # If headline has "at <Company>" or "@ <Company>"
        if headline and not company:
            at_match = re.search(r"\b(?:at|@)\s+([A-Z][a-zA-Z0-9\s]+)", headline)
            if at_match:
                company = at_match.group(1).strip()

        # Sanity check name: between 2 and 60 chars, not generic directory
        if len(name) < 2 or len(name) > 60 or "linkedin" in name.lower() or "top " in name.lower():
            return None, None, None

        return name, company, headline

    def _extract_location(self, text: str, intent: QueryIntent) -> str | None:
        """Extract location if mentioned in snippet."""
        if not text:
            return intent.location.display() or None

        # Match "Location: San Francisco, CA" or "Based in Austin, Texas"
        loc_match = re.search(
            r"(?:Location[:\s]+|Based in\s+|Located in\s+|Greater\s+)([A-Z][a-zA-Z\s]+(?:,\s*[A-Z]{2}|,\s*[A-Z][a-zA-Z]+)?(?:\s+Area)?)",
            text,
            flags=re.IGNORECASE,
        )
        if loc_match:
            candidate = loc_match.group(1).strip()
            candidate = candidate.split("\n")[0].split("\r")[0].strip()
            candidate = re.sub(r"\s+(?:Experience|Education|Connections|About|Activity|Contact|United States).*$", "", candidate, flags=re.IGNORECASE).strip()
            if len(candidate) > 2 and not candidate.lower().startswith("linkedin"):
                return candidate

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

    def _extract_handle(self, url: str) -> str | None:
        match = re.search(r"linkedin\.com/(?:in|company)/([a-zA-Z0-9_-]+)", url)
        return match.group(1) if match else None


# Extend TavilySearchResult with helper
def _tavily_snippet_helper(self: TavilySearchResult) -> str:
    return self.content or ""


TavilySearchResult.snippet_or_content = _tavily_snippet_helper  # type: ignore[attr-defined]
