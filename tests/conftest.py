"""Pytest fixtures and configuration."""

import pytest
import httpx

from app.main import app


@pytest.fixture
async def async_client():
    """Async test client for testing FastAPI endpoints via ASGI."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
