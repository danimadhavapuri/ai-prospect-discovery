"""Profile deduplication and entity resolution service.

Consolidates multiple profiles of the same individual/entity using corroborating
signals (handles, domains, matching emails/phones, bio/location/company overlap)
while strictly avoiding false merges of distinct individuals who share common names.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from app.schemas import CandidateProfile, Prospect, SocialLink

logger = logging.getLogger("prospect_discovery.dedup")


class DeduplicationService:
    """Intelligent entity resolution and prospect consolidation engine."""

    def deduplicate(self, candidates: list[CandidateProfile]) -> list[Prospect]:
        """Group candidate profiles into consolidated Prospects using corroborating signals."""
        if not candidates:
            return []

        # Disjoint set / clustering
        clusters: list[list[CandidateProfile]] = []

        for cand in candidates:
            matched_cluster_idx: int | None = None
            for idx, cluster in enumerate(clusters):
                # Compare candidate against all members of cluster
                if any(self._is_same_entity(cand, member) for member in cluster):
                    # Check if there are any hard conflicts with any member of cluster
                    has_conflict = any(self._has_hard_conflict(cand, member) for member in cluster)
                    if not has_conflict:
                        matched_cluster_idx = idx
                        break

            if matched_cluster_idx is not None:
                clusters[matched_cluster_idx].append(cand)
            else:
                clusters.append([cand])

        # Consolidate each cluster into a single Prospect
        prospects: list[Prospect] = []
        for cluster in clusters:
            prospect = self._merge_cluster(cluster)
            if prospect:
                prospects.append(prospect)

        return prospects

    def _is_same_entity(self, c1: CandidateProfile, c2: CandidateProfile) -> bool:
        """Evaluate if two candidate profiles belong to the same entity based on strong signals."""
        # Exact URL match
        if c1.profile_url and c2.profile_url and c1.profile_url.lower() == c2.profile_url.lower():
            return True

        # Shared verified email address
        if c1.emails and c2.emails and (set(c1.emails) & set(c2.emails)):
            return True

        # Shared verified WhatsApp link
        if c1.whatsapp_links and c2.whatsapp_links and (set(c1.whatsapp_links) & set(c2.whatsapp_links)):
            return True

        # Shared unique handle across platforms (e.g. @janedoe on X and Threads/Instagram)
        if c1.handle and c2.handle and len(c1.handle) >= 3:
            if c1.handle.lower() == c2.handle.lower():
                # Verify names don't drastically contradict
                if self._names_compatible(c1.name, c2.name):
                    return True

        # Shared unique domain
        if c1.domain and c2.domain and len(c1.domain) > 3:
            if c1.domain.lower() == c2.domain.lower():
                return True

        # Same Name + Strong Context Overlap (same company or matching location + matching role/snippet)
        name_sim = self._name_similarity(c1.name, c2.name)
        if name_sim >= 0.85:
            # 1. Direct company match
            if c1.company and c2.company:
                comp_sim = self._name_similarity(c1.company, c2.company)
                if comp_sim >= 0.8:
                    return True

            # 2. Company mentioned in other profile snippet
            if c1.company and len(c1.company) > 2 and c1.company.lower() in (c2.snippet or "").lower():
                return True
            if c2.company and len(c2.company) > 2 and c2.company.lower() in (c1.snippet or "").lower():
                return True

            # 3. Matching location and corroborating context
            if c1.location and c2.location and self._locations_match(c1.location, c2.location):
                # Handle similarity (e.g. sarahconnor vs sarahconnor_ai)
                if c1.handle and c2.handle:
                    h1, h2 = c1.handle.lower(), c2.handle.lower()
                    if h1 in h2 or h2 in h1:
                        return True

                # Title or snippet overlap
                corpus1 = f"{c1.title or ''} {c1.snippet or ''}".lower()
                corpus2 = f"{c2.title or ''} {c2.snippet or ''}".lower()
                words1 = set(re.findall(r"\b[a-z]{4,}\b", corpus1))
                words2 = set(re.findall(r"\b[a-z]{4,}\b", corpus2))
                # Remove location words
                words1 -= set(re.findall(r"\b[a-z]{4,}\b", c1.location.lower()))
                words2 -= set(re.findall(r"\b[a-z]{4,}\b", c2.location.lower()))
                if len(words1 & words2) >= 1:
                    return True

        return False

    def _has_hard_conflict(self, c1: CandidateProfile, c2: CandidateProfile) -> bool:
        """Check for contradictory facts indicating two distinct individuals with the same name."""
        # 1. Location conflict: different cities/countries
        if c1.location and c2.location:
            if not self._locations_match(c1.location, c2.location):
                # Distinct locations mean distinct people (e.g. San Francisco vs London)
                return True

        # 2. Company conflict: clearly different employers
        if c1.company and c2.company:
            c1_comp = c1.company.strip().lower()
            c2_comp = c2.company.strip().lower()
            if c1_comp != c2_comp and len(c1_comp) > 2 and len(c2_comp) > 2:
                if c1_comp not in c2_comp and c2_comp not in c1_comp:
                    return True

        # 3. Handle conflict: completely different handles on the same platform
        if c1.platform == c2.platform and c1.handle and c2.handle:
            if c1.handle.lower() != c2.handle.lower():
                return True

        return False

    def _merge_cluster(self, cluster: list[CandidateProfile]) -> Prospect | None:
        """Merge a group of candidate profiles into a single verified Prospect."""
        if not cluster:
            return None

        # Choose best name: longest / most descriptive real name (avoid handles if full name exists)
        best_name = cluster[0].name
        for cand in cluster:
            if len(cand.name) > len(best_name) and not cand.name.startswith("@"):
                best_name = cand.name

        # Choose best location
        best_location = ""
        for cand in cluster:
            if cand.location and len(cand.location) > len(best_location):
                best_location = cand.location

        # Consolidate social links
        social_links: list[SocialLink] = []
        seen_links: set[tuple[str, str]] = set()

        def add_link(platform: Any, url: str) -> None:
            if not url or not platform:
                return
            clean_u = url.strip()
            # Normalize key by stripping trailing slash and lowercasing
            norm_key = (str(platform), clean_u.rstrip("/").lower())
            if norm_key not in seen_links:
                seen_links.add(norm_key)
                social_links.append(SocialLink(platform=platform, link=clean_u))

        for cand in cluster:
            # Add primary platform URL
            if cand.profile_url:
                add_link(cand.platform, cand.profile_url)

            # Add emails
            for email in cand.emails:
                add_link("Email", email)

            # Add WhatsApp links
            for wa in cand.whatsapp_links:
                add_link("WhatsApp", wa)

            # Add extra extracted links
            for extra in cand.additional_links:
                add_link(extra.platform, extra.link)

        return Prospect(
            name=best_name,
            location=best_location,
            social_link=social_links,
        )

    def _name_similarity(self, a: str | None, b: str | None) -> float:
        if not a or not b:
            return 0.0
        norm_a = re.sub(r"[^\w\s]", "", a.lower()).strip()
        norm_b = re.sub(r"[^\w\s]", "", b.lower()).strip()
        if norm_a == norm_b:
            return 1.0
        return SequenceMatcher(None, norm_a, norm_b).ratio()

    def _names_compatible(self, a: str | None, b: str | None) -> bool:
        if not a or not b:
            return True
        norm_a = a.lower().strip()
        norm_b = b.lower().strip()
        if norm_a in norm_b or norm_b in norm_a:
            return True
        return self._name_similarity(a, b) >= 0.7

    def _locations_match(self, loc1: str, loc2: str) -> bool:
        """Check if two location strings are compatible or overlapping."""
        l1 = loc1.lower().strip()
        l2 = loc2.lower().strip()

        if l1 == l2 or l1 in l2 or l2 in l1:
            return True

        # Extract city tokens
        toks1 = set(re.findall(r"\b[a-zA-Z]{3,}\b", l1))
        toks2 = set(re.findall(r"\b[a-zA-Z]{3,}\b", l2))

        # Ignore noise words
        noise = {"area", "greater", "city", "region", "based", "located"}
        toks1 -= noise
        toks2 -= noise

        return bool(toks1 & toks2)


# Singleton instance
deduplication_service = DeduplicationService()
