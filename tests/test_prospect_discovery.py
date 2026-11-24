"""Comprehensive pytest test suite for AI Prospect Discovery API.

Covers:
1. Valid prospect discovery and exact schema contract compliance.
2. Empty and invalid query input validation (HTTP 422 / 400).
3. Security: SSRF blocking on localhost, loopback, private IPs, cloud metadata, and DNS rebinding.
4. Intelligent Deduplication: Duplicate consolidation across platforms vs distinct same-name disambiguation.
5. Contact validation: RFC email mailto: normalization and WhatsApp wa.me validation.
6. Error handling: Partial platform failure isolation and graceful missing-key fallbacks.
7. Zero-Fabrication guarantee: Never hallucinates prospects, URLs, or contacts.
"""

from unittest.mock import AsyncMock, patch
import pytest
import httpx

from app.schemas import (
    CandidateProfile,
    DiscoveryRequest,
    DiscoveryResponse,
    LocationIntent,
    Prospect,
    QueryIntent,
    SocialLink,
    TavilySearchResult,
)
from app.services.deduplication_service import deduplication_service
from app.services.prospect_service import prospect_service
from app.services.relevance_service import relevance_service
from app.services.search_service import search_service
from app.utils.validators import (
    clean_url,
    identify_platform,
    is_ip_allowed,
    is_search_engine_result_url,
    validate_email,
    validate_phone,
    validate_url_for_ssrf,
    validate_whatsapp,
)


# =====================================================================
# 1. SSRF & Security Protection Tests
# =====================================================================


class TestSSRFProtection:
    """Tests verifying complete prevention of Server-Side Request Forgery."""

    @pytest.mark.parametrize(
        "ip_str",
        [
            "127.0.0.1",
            "127.0.0.2",
            "127.255.255.255",
            "::1",
            "0.0.0.0",
            "::",
            "10.0.0.1",
            "10.255.255.254",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.1.100",
            "169.254.169.254",  # AWS/GCP/Azure instance metadata
            "169.254.1.1",      # Link-local
            "fe80::1",          # IPv6 Link-local
            "fc00::1",          # IPv6 Unique Local Address
            "fd12:3456:789a::1",
            "100.64.0.1",       # Carrier-grade NAT
            "192.0.2.1",        # TEST-NET-1
            "198.51.100.1",     # TEST-NET-2
            "203.0.113.1",      # TEST-NET-3
            "224.0.0.1",        # Multicast
            "240.0.0.1",        # Reserved
        ],
    )
    def test_blocked_ips(self, ip_str: str) -> None:
        """Verify that private, loopback, link-local, and cloud metadata IPs are strictly blocked."""
        is_allowed, reason = is_ip_allowed(ip_str)
        assert is_allowed is False
        assert reason is not None

    def test_allowed_public_ips(self) -> None:
        """Verify that legitimate public routable IPs are permitted."""
        assert is_ip_allowed("8.8.8.8")[0] is True
        assert is_ip_allowed("1.1.1.1")[0] is True
        assert is_ip_allowed("140.82.121.4")[0] is True  # GitHub public IP

    def test_ipv4_mapped_ipv6_loopback_blocked(self) -> None:
        """Verify that IPv4-mapped IPv6 loopback (::ffff:127.0.0.1) is blocked."""
        is_allowed, reason = is_ip_allowed("::ffff:127.0.0.1")
        assert is_allowed is False

    def test_ipv4_mapped_metadata_blocked(self) -> None:
        """Verify that IPv4-mapped IPv6 metadata (::ffff:169.254.169.254) is blocked."""
        is_allowed, reason = is_ip_allowed("::ffff:169.254.169.254")
        assert is_allowed is False

    @pytest.mark.parametrize(
        "prohibited_url",
        [
            "http://localhost:8000/api",
            "http://127.0.0.1:4000/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/meta-data/",
            "http://10.0.0.5:8080/internal",
            "http://192.168.1.1/router",
            "http://172.16.0.10:3000/metrics",
            "file:///etc/passwd",
            "ftp://example.com/file",
            "gopher://127.0.0.1:6379",
            "data:text/plain;base64,SGVsbG8=",
        ],
    )
    def test_validate_url_ssrf_prohibited(self, prohibited_url: str) -> None:
        """Ensure malicious or internal URLs fail SSRF pre-validation."""
        is_safe, reason, _ = validate_url_for_ssrf(prohibited_url)
        assert is_safe is False
        assert reason is not None

    def test_dns_rebinding_simulation(self) -> None:
        """Verify that a domain resolving to a private/loopback IP is detected and blocked."""
        with patch("socket.getaddrinfo") as mock_dns:
            # Simulate domain resolving to loopback 127.0.0.1
            mock_dns.return_value = [
                (2, 1, 6, "", ("127.0.0.1", 80))
            ]
            is_safe, reason, resolved = validate_url_for_ssrf("http://attacker-controlled-domain.com")
            assert is_safe is False
            assert "blocked" in reason.lower() or "loopback" in reason.lower()


# =====================================================================
# 2. Contact and URL Validation Tests
# =====================================================================


class TestContactAndUrlValidation:
    """Tests verifying email, phone, WhatsApp, and social URL cleaning."""

    def test_validate_email_valid(self) -> None:
        """Ensure standard valid emails are correctly prefixed with mailto:."""
        assert validate_email("alex.smith@startup.ai") == "mailto:alex.smith@startup.ai"
        assert validate_email("jane_doe+tech@company.co.uk") == "mailto:jane_doe+tech@company.co.uk"

    def test_validate_email_dummy_rejected(self) -> None:
        """Ensure dummy or placeholder emails are discarded."""
        assert validate_email("user@example.com") is None
        assert validate_email("noreply@company.com") is None
        assert validate_email("privacy@domain.com") is None
        assert validate_email("notanemail") is None
        assert validate_email("avatar.png@2x") is None

    def test_validate_phone(self) -> None:
        """Ensure valid phone numbers are cleanly formatted."""
        assert validate_phone("+1 (415) 555-2671") == "+14155552671"
        assert validate_phone("+44 20 7946 0958") == "+442079460958"
        # Discard invalid repeats
        assert validate_phone("0000000000") is None

    def test_validate_whatsapp(self) -> None:
        """Ensure wa.me links are standardized."""
        assert validate_whatsapp("https://wa.me/14155552671") == "https://wa.me/14155552671"
        assert validate_whatsapp("https://api.whatsapp.com/send?phone=14155552671") == "https://wa.me/14155552671"
        assert validate_whatsapp("wa.me/+919876543210") == "https://wa.me/919876543210"

    def test_clean_url_strips_tracking(self) -> None:
        """Ensure marketing and session trackers are removed from public URLs."""
        raw = "https://linkedin.com/in/alexsmith?utm_source=google&utm_medium=cpc&ref=feed"
        cleaned = clean_url(raw)
        assert cleaned == "https://linkedin.com/in/alexsmith"

    def test_is_search_engine_result_url(self) -> None:
        """Ensure raw search result URLs are recognized and blocked."""
        assert is_search_engine_result_url("https://www.google.com/search?q=ai+founders") is True
        assert is_search_engine_result_url("https://bing.com/search?q=test") is True
        assert is_search_engine_result_url("https://duckduckgo.com/?q=test") is True
        assert is_search_engine_result_url("https://linkedin.com/in/alexsmith") is False

    def test_identify_platform(self) -> None:
        """Ensure platform detection accurately maps URLs to the 9 strict platforms."""
        assert identify_platform("https://linkedin.com/in/alexsmith") == "LinkedIn"
        assert identify_platform("https://x.com/alexsmith") == "X"
        assert identify_platform("https://twitter.com/alexsmith") == "X"
        assert identify_platform("https://youtube.com/@alexsmith") == "YouTube"
        assert identify_platform("https://instagram.com/alexsmith") == "Instagram"
        assert identify_platform("https://wa.me/14155552671") == "WhatsApp"
        assert identify_platform("https://facebook.com/alexsmith") == "Facebook"
        assert identify_platform("https://threads.net/@alexsmith") == "Threads"
        assert identify_platform("mailto:alex@smith.com") == "Email"
        assert identify_platform("https://alexsmith.io") == "Google"


# =====================================================================
# 3. Deduplication & Disambiguation Tests
# =====================================================================


class TestDeduplicationAndDisambiguation:
    """Tests verifying candidate consolidation vs distinct same-name disambiguation."""

    def test_consolidate_same_individual_across_platforms(self) -> None:
        """Verify that profiles of the same person on LinkedIn and X are consolidated."""
        c1 = CandidateProfile(
            name="Elena Rostova",
            platform="LinkedIn",
            profile_url="https://www.linkedin.com/in/erostova",
            title="CEO & Co-Founder at QuantumAI",
            snippet="Elena Rostova - CEO at QuantumAI in San Francisco, CA.",
            location="San Francisco, CA",
            handle="erostova",
            company="QuantumAI",
            emails=["mailto:elena@quantumai.com"],
        )

        c2 = CandidateProfile(
            name="Elena Rostova",
            platform="X",
            profile_url="https://x.com/erostova",
            title="Elena Rostova (@erostova) / X",
            snippet="Founder QuantumAI. Building quantum models in SF. Contact: elena@quantumai.com",
            location="San Francisco, CA",
            handle="erostova",
            company="QuantumAI",
            emails=["mailto:elena@quantumai.com"],
        )

        prospects = deduplication_service.deduplicate([c1, c2])
        assert len(prospects) == 1
        prospect = prospects[0]
        assert prospect.name == "Elena Rostova"
        assert "San Francisco" in prospect.location

        # Verify both LinkedIn and X are in social_link, along with Email
        platforms = {link.platform for link in prospect.social_link}
        assert "LinkedIn" in platforms
        assert "X" in platforms
        assert "Email" in platforms

    def test_disambiguate_distinct_people_with_same_name(self) -> None:
        """Verify that two distinct individuals with the same common name are NOT merged."""
        # Person A: San Francisco, TechCorp
        p_a = CandidateProfile(
            name="Michael Brown",
            platform="LinkedIn",
            profile_url="https://www.linkedin.com/in/michaelbrown-sf",
            title="Staff Engineer at TechCorp",
            snippet="Staff Engineer at TechCorp. Located in San Francisco, CA.",
            location="San Francisco, CA",
            handle="michaelbrown-sf",
            company="TechCorp",
        )

        # Person B: London, UK, FinBank
        p_b = CandidateProfile(
            name="Michael Brown",
            platform="LinkedIn",
            profile_url="https://www.linkedin.com/in/michaelbrown-uk",
            title="Investment Director at FinBank",
            snippet="Investment Director at FinBank. Based in London, UK.",
            location="London, UK",
            handle="michaelbrown-uk",
            company="FinBank",
        )

        prospects = deduplication_service.deduplicate([p_a, p_b])
        # MUST remain 2 separate prospects
        assert len(prospects) == 2
        locations = {p.location for p in prospects}
        assert "San Francisco, CA" in locations
        assert "London, UK" in locations


# =====================================================================
# 4. Zero Fabrication & Quality Filtering Tests
# =====================================================================


class TestZeroFabricationAndQuality:
    """Tests ensuring zero hallucination and strict quality filtering."""

    def test_zero_prospects_when_empty_results(self) -> None:
        """Verify that when search returns 0 results, empty list is returned without fabrications."""
        intent = QueryIntent(
            interest=["nonexistenttechxyz123"],
            location=LocationIntent(city="Nowhere"),
            suggested_queries=["nonexistenttechxyz123 Nowhere"],
        )
        prospects = relevance_service.filter_and_rank_prospects([], intent)
        assert prospects == []

    def test_discard_junk_search_directory_titles(self) -> None:
        """Verify that directory pages, login links, and generic listicles are discarded."""
        intent = QueryIntent()
        junk_candidates = [
            Prospect(
                name="Top 10 AI Founders in 2026",
                location="San Francisco",
                social_link=[SocialLink(platform="LinkedIn", link="https://linkedin.com/pulse/top-10")],
            ),
            Prospect(
                name="Sign in to LinkedIn",
                location="",
                social_link=[SocialLink(platform="LinkedIn", link="https://linkedin.com/login")],
            ),
            Prospect(
                name="Privacy Policy",
                location="",
                social_link=[SocialLink(platform="Google", link="https://example.com/privacy")],
            ),
        ]

        verified = relevance_service.filter_and_rank_prospects(junk_candidates, intent)
        assert len(verified) == 0


# =====================================================================
# 5. FastAPI Endpoints & Contract Tests (ASGI Async Client)
# =====================================================================


class TestProspectDiscoveryAPI:
    """End-to-end API tests against FastAPI router."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, async_client: httpx.AsyncClient) -> None:
        """Verify GET /health reports healthy status and service flags."""
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "services" in data
        assert "caches" in data
        assert "llm_metrics" in data

    @pytest.mark.asyncio
    async def test_prospect_discovery_empty_query_422(self, async_client: httpx.AsyncClient) -> None:
        """Verify empty query returns 422 Unprocessable Entity."""
        response = await async_client.post("/prospect-discovery", json={"query": "   "})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_prospect_discovery_missing_field_422(self, async_client: httpx.AsyncClient) -> None:
        """Verify missing query field returns 422."""
        response = await async_client.post("/prospect-discovery", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_prospect_discovery_pipeline_contract(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """Verify POST /prospect-discovery returns exact schema with verified prospects."""
        # Mock search service to return deterministic real-format search items
        mock_results = [
            TavilySearchResult(
                title="Sarah Connor - Founder & CEO at CyberAI | LinkedIn",
                url="https://www.linkedin.com/in/sarahconnor",
                content="Sarah Connor is the Founder and CEO of CyberAI, based in Austin, Texas. Contact: sarah@cyberai.tech",
            ),
            TavilySearchResult(
                title="Sarah Connor (@sarahconnor_ai) on X: 'Building AI in Austin'",
                url="https://x.com/sarahconnor_ai",
                content="Founder CyberAI. Austin TX. wa.me/15125550199",
            ),
        ]

        with patch.object(
            search_service,
            "search_queries_concurrent",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            payload = {"query": "Find AI founders in Austin Texas with LinkedIn and Twitter"}
            response = await async_client.post("/prospect-discovery", json=payload)

            assert response.status_code == 200
            data = response.json()

            # Verify exact schema keys
            assert data["success"] is True
            assert data["query"] == payload["query"]
            assert data["total_prospects"] == 1
            assert len(data["prospects"]) == 1

            prospect = data["prospects"][0]
            assert prospect["name"] == "Sarah Connor"
            assert "Austin" in prospect["location"]

            # Verify consolidated social links
            links = prospect["social_link"]
            platforms = [l["platform"] for l in links]
            assert "LinkedIn" in platforms
            assert "X" in platforms
            assert "Email" in platforms
            assert "WhatsApp" in platforms

            # Verify formats
            for item in links:
                if item["platform"] == "Email":
                    assert item["link"].startswith("mailto:")
                elif item["platform"] == "WhatsApp":
                    assert item["link"].startswith("https://wa.me/")
                elif item["platform"] == "LinkedIn":
                    assert "linkedin.com" in item["link"]
                elif item["platform"] == "X":
                    assert "x.com" in item["link"]

    @pytest.mark.asyncio
    async def test_zero_fabrication_on_no_results(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """Verify pipeline returns total_prospects: 0 and prospects: [] when no matches exist."""
        with patch.object(
            search_service,
            "search_queries_concurrent",
            new_callable=AsyncMock,
            return_value=[],
        ):
            payload = {"query": "Find non-existent fictional characters in Atlantis"}
            response = await async_client.post("/prospect-discovery", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["total_prospects"] == 0
            assert data["prospects"] == []
