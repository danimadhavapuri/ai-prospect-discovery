"""Security and data validation utilities.

Implements:
1. Strict SSRF protection (IP validation, DNS resolution checks, redirect re-validation, response byte limiting).
2. Public contact format validation (Email RFC-compliant check + mailto: normalization, WhatsApp wa.me normalization).
3. Search engine & platform system URL filtering (disallowing raw search result URLs, login pages, and tracking artifacts).
"""

import ipaddress
import re
import socket
import urllib.parse
from typing import Literal

import httpx

from app.schemas import SocialPlatform

# Blocked Private, Loopback, Link-Local, and Reserved Networks
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # Carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),  # IPv4 Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / Cloud metadata (AWS, GCP, Azure)
    ipaddress.ip_network("172.16.0.0/12"),  # Private Class B
    ipaddress.ip_network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),  # Private Class C
    ipaddress.ip_network("198.18.0.0/15"),  # Network benchmark tests
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6 Networks
    ipaddress.ip_network("::/128"),  # Unspecified
    ipaddress.ip_network("::1/128"),  # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),  # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),  # Link-Local
    ipaddress.ip_network("ff00::/8"),  # Multicast
    ipaddress.ip_network("2001:db8::/32"),  # Documentation
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
]

# Blocked hostnames associated with internal cloud metadata and local instances
BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata.local",
    "instance-data",
    "169.254.169.254",
    "metadata",
    "local",
    "internal",
}

# Raw search engine hosts to filter out per specification
SEARCH_ENGINE_HOSTS = {
    "google.com",
    "www.google.com",
    "bing.com",
    "www.bing.com",
    "duckduckgo.com",
    "search.yahoo.com",
    "yahoo.com",
    "www.yahoo.com",
    "tavily.com",
    "api.tavily.com",
    "baidu.com",
    "www.baidu.com",
    "yandex.com",
    "www.yandex.com",
}

# Strict Email Regex (RFC 5322 compatible subset)
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)

# Dummy/Placeholder email domains and user prefixes to discard
DUMMY_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "domain.com",
    "test.com",
    "sample.com",
    "startup.com",
    "startup-inc.com",
    "yoursite.com",
    "email.com",
    "company.com",
    "sentry.io",
}

DUMMY_EMAIL_PREFIXES = {
    "noreply",
    "no-reply",
    "donotreply",
    "mailer-daemon",
    "postmaster",
    "abuse",
    "privacy",
    "legal",
    "terms",
    "help",
    "support",
    "billing",
    "jobs",
    "careers",
    "press",
}

# Regex for common dummy/placeholder user patterns like john.smith@*, johnsmith@*, etc.
PLACEHOLDER_USER_PATTERNS = [
    r"^john[\._-]?smith(?:[0-9]+)?$",
    r"^jane[\._-]?doe(?:[0-9]+)?$",
    r"^your[\._-]?name(?:[0-9]+)?$",
    r"^user(?:name)?(?:[0-9]+)?$",
    r"^placeholder(?:[0-9]+)?$",
    r"^sample(?:[0-9]+)?$",
    r"^first(?:name)?[\._-]last(?:name)?$",
]


def is_ip_allowed(ip_str: str) -> tuple[bool, str | None]:
    """Verify that an IP address is public and does not belong to blocked/private ranges."""
    try:
        ip = ipaddress.ip_address(ip_str.strip("[]"))
    except ValueError:
        return False, f"Invalid IP address representation: {ip_str}"

    # Handle IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return is_ip_allowed(str(ip.ipv4_mapped))

    # Standard IP flags
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False, f"IP {ip} is private, loopback, link-local, or reserved"

    # Explicit subnet checks
    for network in BLOCKED_IP_NETWORKS:
        if ip in network:
            return False, f"IP {ip} belongs to prohibited network {network}"

    return True, None


def validate_url_for_ssrf(url: str) -> tuple[bool, str | None, list[str]]:
    """Validate a URL against SSRF vulnerabilities before any outbound HTTP connection.

    Checks:
    - Scheme must be strictly 'http' or 'https'.
    - Hostname must exist and not match blocked internal hostnames.
    - Resolves DNS and verifies every resolved IP address is public and non-private.
    """
    if not url or not isinstance(url, str):
        return False, "Empty or non-string URL provided", []

    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception as e:
        return False, f"URL parse failed: {e}", []

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Prohibited scheme: '{scheme}'. Only http and https are allowed.", []

    hostname = parsed.hostname
    if not hostname:
        return False, "URL is missing a valid hostname", []

    hostname_clean = hostname.strip().lower()

    # Blocked hostnames and suffixes
    if hostname_clean in BLOCKED_HOSTNAMES:
        return False, f"Prohibited internal hostname: '{hostname_clean}'", []

    if (
        hostname_clean.endswith(".localhost")
        or hostname_clean.endswith(".local")
        or hostname_clean.endswith(".internal")
    ):
        return False, f"Prohibited internal host domain: '{hostname_clean}'", []

    # Safe DNS resolution and IP verification
    port = parsed.port or (443 if scheme == "https" else 80)
    resolved_ips: list[str] = []

    # If hostname is already a raw IP
    try:
        ip = ipaddress.ip_address(hostname_clean.strip("[]"))
        is_ok, reason = is_ip_allowed(str(ip))
        if not is_ok:
            return False, f"Prohibited destination IP: {reason}", [str(ip)]
        return True, None, [str(ip)]
    except ValueError:
        pass  # Hostname is a domain name, proceed to DNS resolution

    try:
        addr_infos = socket.getaddrinfo(
            hostname_clean, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as e:
        return False, f"DNS resolution failed for '{hostname_clean}': {e}", []
    except Exception as e:
        return False, f"Socket error resolving '{hostname_clean}': {e}", []

    for _, _, _, _, sockaddr in addr_infos:
        ip_candidate = sockaddr[0]
        resolved_ips.append(ip_candidate)
        is_ok, reason = is_ip_allowed(ip_candidate)
        if not is_ok:
            return False, f"DNS resolved to prohibited destination: {reason}", resolved_ips

    if not resolved_ips:
        return False, f"Host '{hostname_clean}' resolved to 0 IP addresses", []

    return True, None, resolved_ips


async def safe_fetch_metadata(
    url: str,
    max_bytes: int = 1_048_576,
    timeout_seconds: float = 5.0,
    max_redirects: int = 3,
) -> tuple[bool, str | None, str | None]:
    """Safely fetch HTML metadata from an external URL with full SSRF protection.

    Features:
    - Pre-fetch SSRF validation.
    - Redirect validation (each hop is re-validated before following).
    - Hard byte limit protection (default 1MB).
    - Strict timeout protection.
    - Zero sensitive error leakage.
    """
    current_url = url
    for _ in range(max_redirects + 1):
        is_safe, reason, _ = validate_url_for_ssrf(current_url)
        if not is_safe:
            return False, f"SSRF blocked: {reason}", None

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout_seconds,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ProspectDiscovery/1.0"},
            ) as client:
                response = await client.get(current_url)

                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return False, "Redirect with missing location header", None
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue

                if response.status_code != 200:
                    return False, f"HTTP {response.status_code}", None

                # Byte limit check
                content_bytes = bytearray()
                async for chunk in response.aiter_bytes():
                    content_bytes.extend(chunk)
                    if len(content_bytes) > max_bytes:
                        return False, "Response exceeded max byte limit (1MB)", None

                text_content = content_bytes.decode("utf-8", errors="replace")
                return True, text_content, str(response.url)

        except (httpx.TimeoutException, TimeoutError):
            return False, "Request timed out", None
        except httpx.RequestError as e:
            return False, f"Network request error: {e.__class__.__name__}", None
        except Exception:
            return False, "Outbound fetch aborted", None

    return False, "Exceeded maximum redirects", None


def validate_email(email: str) -> str | None:
    """Validate email address and return RFC-compliant 'mailto:<email>' string, or None."""
    if not email or not isinstance(email, str):
        return None

    cleaned = email.strip().strip(".,;:()[]{}<>\"'").lower()

    # Discard if contains file extensions (e.g. image.png@2x)
    if any(cleaned.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".css", ".js")):
        return None

    if not EMAIL_REGEX.match(cleaned):
        return None

    user, _, domain = cleaned.partition("@")
    domain = domain.rstrip(".")

    if user in DUMMY_EMAIL_PREFIXES or domain in DUMMY_EMAIL_DOMAINS:
        return None

    # Check for placeholder usernames like john.smith@*, johnsmith@*, etc.
    for pat in PLACEHOLDER_USER_PATTERNS:
        if re.match(pat, user):
            return None

    if len(domain.split(".")) < 2:
        return None

    return f"mailto:{user}@{domain}"


def validate_phone(phone_str: str) -> str | None:
    """Validate phone number format and return cleaned E.164-compatible string, or None."""
    if not phone_str or not isinstance(phone_str, str):
        return None

    cleaned = phone_str.strip()
    digits = re.sub(r"[^\d+]", "", cleaned)

    # Count only digits
    num_digits = len(re.sub(r"\D", "", digits))
    if num_digits < 7 or num_digits > 15:
        return None

    # Filter out repeating digits (e.g., 00000000, 11111111)
    raw_digits = re.sub(r"\D", "", digits)
    if len(set(raw_digits)) <= 1:
        return None

    return digits


def validate_whatsapp(wa_input: str) -> str | None:
    """Extract and validate WhatsApp contact link into standardized 'https://wa.me/<digits>'."""
    if not wa_input or not isinstance(wa_input, str):
        return None

    cleaned = wa_input.strip()

    # If it's a URL like https://wa.me/1234567890 or https://api.whatsapp.com/send?phone=1234567890
    match_wa = re.search(r"wa\.me/(\+?\d+)", cleaned, re.IGNORECASE)
    if match_wa:
        digits = re.sub(r"\D", "", match_wa.group(1))
        if 7 <= len(digits) <= 15:
            return f"https://wa.me/{digits}"

    match_api = re.search(r"api\.whatsapp\.com/send\?(?:[^&]*&)*phone=(\+?\d+)", cleaned, re.IGNORECASE)
    if match_api:
        digits = re.sub(r"\D", "", match_api.group(1))
        if 7 <= len(digits) <= 15:
            return f"https://wa.me/{digits}"

    # If it's a direct phone number marked as WhatsApp
    direct_digits = re.sub(r"\D", "", cleaned)
    if 7 <= len(direct_digits) <= 15 and ("whatsapp" in cleaned.lower() or "wa.me" in cleaned.lower()):
        return f"https://wa.me/{direct_digits}"

    return None


def is_search_engine_result_url(url: str) -> bool:
    """Return True if URL is a search engine result page (google.com/search, etc.)."""
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()

        for se_host in SEARCH_ENGINE_HOSTS:
            if host == se_host or host.endswith("." + se_host):
                if "/search" in path or "/url" in path or path in ("", "/"):
                    return True
                return True
    except Exception:
        return True
    return False


def clean_url(url: str) -> str | None:
    """Clean tracking params, validate URL scheme, and ensure it is not a raw search engine page."""
    if not url or not isinstance(url, str):
        return None

    cleaned = url.strip()
    if is_search_engine_result_url(cleaned):
        return None

    try:
        parsed = urllib.parse.urlsplit(cleaned)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return None

        # Filter out tracking query params
        tracking_params = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "fbclid",
            "igshid",
            "ref",
            "rc",
            "s",
            "t",
        }

        query_tuples = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered_query = [
            (k, v) for k, v in query_tuples if k.lower() not in tracking_params
        ]
        new_query = urllib.parse.urlencode(filtered_query)

        rebuilt = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, new_query, "")
        )
        return rebuilt.rstrip("/") if parsed.path not in ("", "/") else rebuilt
    except Exception:
        return None


def identify_platform(url: str) -> SocialPlatform | None:
    """Identify which of the 9 exact supported platforms a URL belongs to.

    Supported platforms:
    - Google
    - LinkedIn
    - X
    - YouTube
    - Instagram
    - WhatsApp
    - Facebook
    - Email
    - Threads
    """
    if not url:
        return None

    lower = url.lower()

    if lower.startswith("mailto:"):
        return "Email"

    if "wa.me/" in lower or "api.whatsapp.com" in lower:
        return "WhatsApp"

    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
    except Exception:
        return None

    # LinkedIn
    if "linkedin.com" in host:
        return "LinkedIn"

    # X / Twitter
    if host in ("x.com", "twitter.com") or host.endswith(".x.com") or host.endswith(".twitter.com"):
        return "X"

    # YouTube
    if host in ("youtube.com", "youtu.be") or host.endswith(".youtube.com"):
        return "YouTube"

    # Instagram
    if "instagram.com" in host:
        return "Instagram"

    # Threads
    if "threads.net" in host:
        return "Threads"

    # Facebook
    if "facebook.com" in host or "fb.com" in host:
        return "Facebook"

    # Google (Official website, Google Business Profile, Google Maps listing)
    return "Google"
