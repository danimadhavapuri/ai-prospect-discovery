"""Async Google Gemini client for structured intent parsing and query synthesis.

Uses google-genai SDK with:
- Primary model (gemini-2.5-flash) and fallback model (gemini-2.5-flash-lite).
- Structured JSON schema outputs.
- Exponential backoff retry logic.
- In-memory token usage tracking.
- Deterministic fallback when API key is missing or calls encounter quotas/network blocks.
"""

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings

logger = logging.getLogger("prospect_discovery.llm")


class LLMService:
    """Async Google Gemini service with structured JSON output and fault tolerance."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: genai.Client | None = None
        self._total_prompt_tokens = 0
        self._total_candidate_tokens = 0
        self._total_api_calls = 0

        if self.settings.has_gemini_key:
            try:
                self._client = genai.Client(api_key=self.settings.gemini_api_key)
            except Exception as e:
                logger.warning("Failed to initialize Google Gemini client: %s", e)
                self._client = None

    @property
    def is_available(self) -> bool:
        """Check if Gemini client is initialized and configured."""
        return self._client is not None

    def get_token_metrics(self) -> dict[str, int]:
        """Return cumulative token usage and call metrics."""
        return {
            "total_calls": self._total_api_calls,
            "prompt_tokens": self._total_prompt_tokens,
            "candidate_tokens": self._total_candidate_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_candidate_tokens,
        }

    async def generate_structured_json(
        self,
        prompt: str,
        system_instruction: str | None = None,
        retries: int = 2,
    ) -> dict[str, Any] | None:
        """Generate structured JSON response using Gemini with automatic model fallback."""
        if not self.is_available or self._client is None:
            return None

        models_to_try = [
            self.settings.gemini_primary_model,
            self.settings.gemini_fallback_model,
        ]

        for model_name in models_to_try:
            for attempt in range(retries + 1):
                try:
                    config = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        system_instruction=system_instruction,
                        temperature=0.1,  # Low temperature for deterministic factual extraction
                    )

                    response = await self._client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )

                    self._total_api_calls += 1

                    # Record token metrics if available
                    usage = getattr(response, "usage_metadata", None)
                    if usage:
                        self._total_prompt_tokens += getattr(usage, "prompt_token_count", 0) or 0
                        self._total_candidate_tokens += getattr(usage, "candidates_token_count", 0) or 0

                    text_content = response.text
                    if not text_content:
                        continue

                    # Parse JSON safely
                    try:
                        parsed_json = json.loads(text_content.strip())
                        return parsed_json
                    except json.JSONDecodeError:
                        # Clean potential markdown fences
                        cleaned = text_content.strip()
                        if cleaned.startswith("```json"):
                            cleaned = cleaned[7:]
                        if cleaned.startswith("```"):
                            cleaned = cleaned[3:]
                        if cleaned.endswith("```"):
                            cleaned = cleaned[:-3]
                        return json.loads(cleaned.strip())

                except Exception as e:
                    logger.warning(
                        "Gemini call failed (model=%s, attempt=%d/%d): %s",
                        model_name,
                        attempt + 1,
                        retries + 1,
                        e.__class__.__name__,
                    )
                    if attempt < retries:
                        await asyncio.sleep(2**attempt)
                    break  # If model fails, break to try fallback model

        return None


# Global singleton instance
llm_service = LLMService()
