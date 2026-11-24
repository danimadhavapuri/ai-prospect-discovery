"""Data cleaning and normalization utilities.

Provides entity name cleaning, invisible Unicode stripping, and location
normalization to eliminate noisy search snippet artifacts while strictly
preserving verified, zero-fabrication prospects.
"""

import re
import urllib.parse

# Invisible Unicode characters and directional formatting marks
INVISIBLE_UNICODE_CHARS = [
    "\u200e",  # Left-to-Right Mark (LRM)
    "\u200f",  # Right-to-Left Mark (RLM)
    "\u202a",  # Left-to-Right Embedding (LRE)
    "\u202b",  # Right-to-Left Embedding (RLE)
    "\u202c",  # Pop Directional Formatting (PDF)
    "\u202d",  # Left-to-Right Override (LRO)
    "\u202e",  # Right-to-Left Override (RLO)
    "\u2066",  # Left-to-Right Isolate (LRI)
    "\u2067",  # Right-to-Left Isolate (RLI)
    "\u2068",  # First Strong Isolate (FSI)
    "\u2069",  # Pop Directional Isolate (PDI)
    "\ufeff",  # Zero Width No-Break Space (BOM)
    "\u200b",  # Zero Width Space
    "\u200c",  # Zero Width Non-Joiner (ZWNJ)
    "\u200d",  # Zero Width Joiner (ZWJ)
    "\u00a0",  # Non-breaking space
]

# Generic navigation, boilerplate, and search portal titles that should never be standalone names
BOILERPLATE_TITLE_PATTERNS = {
    "contact",
    "contact us",
    "contact-us",
    "contact me",
    "get in touch",
    "front page",
    "home",
    "homepage",
    "home page",
    "about",
    "about us",
    "about-us",
    "about me",
    "privacy policy",
    "privacy",
    "terms",
    "terms of service",
    "terms of use",
    "terms and conditions",
    "terms & conditions",
    "overview",
    "welcome",
    "index",
    "careers",
    "jobs",
    "help",
    "support",
    "faq",
    "login",
    "log in",
    "signin",
    "sign in",
    "signup",
    "sign up",
    "search results",
    "feed",
    "menu",
    "services",
    "our services",
    "products",
}

# Non-geographic keywords extracted by mistake from page headers or CV badges
NON_GEOGRAPHIC_STRINGS = {
    "level",
    "company name",
    "experience",
    "education",
    "connections",
    "skills",
    "location",
    "united states experience",
    "experience united states",
    "profile",
    "profile overview",
    "contact info",
    "contact information",
    "view profile",
}

# Known truncated 2-letter search snippet abbreviations and their standard expansions
LOCATION_CORRECTIONS = [
    # Washington DC
    (r"\bthe\s+washington\b", "Washington, DC"),
    (r"\bwashington,?\s+di(?:st(?:rict)?)?\b", "Washington, DC"),
    (r"\bwashington,?\s+d\.?c?\.?\b", "Washington, DC"),
    (r"\bwashington\s+di\b", "Washington, DC"),
    # New York NY
    (r"\bnew\s+york,?\s+ne(?:w)?\b", "New York, NY"),
    (r"\bnew\s+york\s+ne\b", "New York, NY"),
    (r"\bnew\s+york,?\s+n\.?y?\.?\b", "New York, NY"),
    (r",\s+ne\b", ", NY"),
    # Dubai UAE
    (r"\bdubai,?\s+du(?:bai)?\b", "Dubai, UAE"),
    (r"\bdubai\s+du\b", "Dubai, UAE"),
    (r"\bdubai,?\s+un(?:ited)?(?:\s+arab(?:\s+emirates)?)?\b", "Dubai, UAE"),
    (r"\bdubai\s+un\b", "Dubai, UAE"),
    (r"\bdubai,?\s+uae\b", "Dubai, UAE"),
    # Ahmedabad / India
    (r"\bahmedabad,?\s+gu(?:j(?:arat)?)?\b", "Ahmedabad, Gujarat, India"),
    (r"\bahmedabad\s+gu\b", "Ahmedabad, Gujarat, India"),
    (r",\s+bi\b", ", Bihar, India"),
    (r",\s+gu\b", ", Gujarat, India"),
    # London UK
    (r"\blondon,?\s+en(?:g(?:land)?)?\b", "London, UK"),
    (r"\blondon\s+en\b", "London, UK"),
    (r"\blondon,?\s+uk\b", "London, UK"),
    (r"\blondon,?\s+united\s+kingdom\b", "London, UK"),
    # California
    (r"\bsan\s+francisco,?\s+ca(?:lif(?:ornia)?)?\b", "San Francisco, CA"),
    (r"\blos\s+angeles,?\s+ca(?:lif(?:ornia)?)?\b", "Los Angeles, CA"),
]


def strip_invisible_unicode(text: str) -> str:
    """Remove invisible Unicode directional formatting marks, zero-width characters, and normalize spaces."""
    if not text:
        return ""
    cleaned = text
    for ch in INVISIBLE_UNICODE_CHARS:
        cleaned = cleaned.replace(ch, " " if ch == "\u00a0" else "")
    # Normalize multiple whitespace into single space
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def clean_entity_name(raw_name: str | None) -> str | None:
    """Clean and extract a verified person or organization name.

    Rules:
    1. Strips invisible Unicode directional marks (\u200e, \u200f, etc.).
    2. Drops raw URLs (e.g. 'https://wa.me/...', 'http://...').
    3. Drops pure generic boilerplate titles ('Contact', 'Contact Us', 'Home', 'Privacy Policy').
    4. Extracts real organization name if compounded with boilerplate (e.g.
       'Contact us – Rags To Riches Restaurant' -> 'Rags To Riches Restaurant').
    5. Strips trailing platform suffixes (' - X', ' | LinkedIn', ' - YouTube', etc.).
    6. Returns None if no real name can be verified, so unverified prospects are dropped.
    """
    if not raw_name or not isinstance(raw_name, str):
        return None

    cleaned = strip_invisible_unicode(raw_name)
    if not cleaned:
        return None

    # Reject raw URLs immediately
    url_low = cleaned.lower()
    if (
        url_low.startswith("http://")
        or url_low.startswith("https://")
        or url_low.startswith("wa.me/")
        or url_low.startswith("www.")
        or "wa.me/" in url_low
        or "api.whatsapp.com" in url_low
    ):
        return None

    # Check full string against boilerplate patterns first
    if cleaned.lower() in BOILERPLATE_TITLE_PATTERNS:
        return None

    # Strip trailing platform suffixes
    cleaned = re.sub(
        r"\s*(?:[•\-|–—:]|\s+on\s+)\s*(?:LinkedIn|X|Twitter|YouTube|Instagram|Facebook|Threads|WhatsApp)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"\s*\|\s*(?:LinkedIn|X|Twitter|YouTube|Instagram|Facebook|Threads|WhatsApp).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"\s*[-|–—:]?\s*(?:Official\s+(?:Site|Website|Page)|Home|About\s+Us|Contact\s+Us|Front\s+Page)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    if cleaned.lower() in BOILERPLATE_TITLE_PATTERNS:
        return None

    # Split compound titles on standard separators: en-dash, em-dash, hyphen, pipe, bullet, colon
    parts = re.split(r"\s*[–—|•·»«]\s*|\s+-\s+|\s*:\s+", cleaned)
    parts = [p.strip() for p in parts if p.strip()]

    candidate_name: str | None = None

    if len(parts) > 1:
        # Check each part. If one is boilerplate (e.g. 'Contact us', 'Home', 'About Us'), take the other
        valid_parts = []
        for p in parts:
            p_low = p.lower()
            if p_low in BOILERPLATE_TITLE_PATTERNS:
                continue
            # Also check if it's "Welcome to X" or starts with "Contact us at"
            p_clean = re.sub(r"^(?:Contact\s+us\s+at|Welcome\s+to(?:\s+the)?)\s+", "", p, flags=re.IGNORECASE).strip()
            if p_clean and p_clean.lower() not in BOILERPLATE_TITLE_PATTERNS and len(p_clean) >= 2:
                valid_parts.append(p_clean)

        if valid_parts:
            # Prefer the first non-boilerplate part (often the brand or person)
            candidate_name = valid_parts[0]
    elif parts:
        candidate = parts[0]
        if candidate.lower() in BOILERPLATE_TITLE_PATTERNS:
            return None
        candidate = re.sub(r"^(?:Welcome\s+to(?:\s+the)?|Contact\s+us\s+at)\s+", "", candidate, flags=re.IGNORECASE).strip()
        candidate_name = candidate

    if not candidate_name:
        return None

    candidate_name = strip_invisible_unicode(candidate_name)
    candidate_name = candidate_name.strip(" -–—|:.,;'\"()[]{}")

    # Reject if it matches boilerplate
    if candidate_name.lower() in BOILERPLATE_TITLE_PATTERNS:
        return None

    # Reject if it's purely punctuation, digits, or too short/long
    if len(candidate_name) < 2 or len(candidate_name) > 70:
        return None

    # Reject if it contains no letters (e.g. "+971 50 123 4567")
    if not re.search(r"[a-zA-Z]", candidate_name):
        return None

    return candidate_name


def normalize_location(
    location: str | None,
    query_intent_location: str | None = None,
    content: str | None = None,
) -> str | None:
    """Normalize extracted location and fix truncated search snippet artifacts.

    Rules:
    1. Fixes truncated 2-letter snippet artifacts:
       'Washington, Di' -> 'Washington, DC'
       'New York, Ne' -> 'New York, NY'
       'Dubai, Du' / 'Dubai, Un' -> 'Dubai, UAE'
       'Ahmedabad, Gu' -> 'Ahmedabad, Gujarat, India'
       'London, En' -> 'London, UK'
       'the Washington' -> 'Washington, DC'
    2. Rejects non-geographic strings like 'Level', 'Company Name', 'Experience'.
    3. Strips trailing snippet artifacts like '\\nExperience', 'United States Experience'.
    4. Falls back to verified query location only when the content explicitly confirms that city/country.
    """
    cleaned: str | None = None

    if location and isinstance(location, str):
        candidate = strip_invisible_unicode(location)
        candidate = candidate.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        candidate = re.sub(r"\s+", " ", candidate).strip()

        # Check against non-geographic strings immediately
        if candidate.lower() in NON_GEOGRAPHIC_STRINGS:
            return None

        # Strip common trailing LinkedIn snippet metadata
        candidate = re.sub(
            r"\s+(?:Experience|Education|Connections|About|Activity|Contact|Skills|Company Name|Level)\b.*$",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip()
        candidate = re.sub(r"\s+(?:United States|US)\s+Experience.*$", "", candidate, flags=re.IGNORECASE).strip()
        candidate = candidate.strip(" ,;-–—|/\\")

        # Check against non-geographic strings again after stripping
        if candidate.lower() not in NON_GEOGRAPHIC_STRINGS and len(candidate) >= 2:
            cleaned = candidate

    # Apply known 2-letter and truncated location corrections
    if cleaned:
        for pattern, replacement in LOCATION_CORRECTIONS:
            if re.search(pattern, cleaned, flags=re.IGNORECASE):
                cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
                break

    # If location is missing or was rejected, check if query location can be safely confirmed by content
    if not cleaned and query_intent_location and content:
        content_low = content.lower()
        query_loc_low = query_intent_location.lower()

        # Only fall back if the content explicitly confirms the target city or country
        cities_countries = [c.strip() for c in query_loc_low.split(",") if len(c.strip()) >= 3]
        if any(place in content_low for place in cities_countries):
            cleaned = query_intent_location

    return cleaned if cleaned and len(cleaned) >= 2 else None
