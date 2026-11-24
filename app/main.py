"""AI-Powered Multi-Platform Prospect Discovery API.

Production-grade FastAPI application implementing verified, zero-fabrication
prospect discovery across Google, LinkedIn, X, YouTube, Instagram, WhatsApp,
Facebook, Email, and Threads.
"""

import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.schemas import DiscoveryRequest, DiscoveryResponse
from app.services.llm_service import llm_service
from app.services.prospect_service import prospect_service
from app.utils.cache import query_intent_cache, search_response_cache

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("prospect_discovery.api")

settings = get_settings()

app = FastAPI(
    title="AI-Powered Multi-Platform Prospect Discovery API",
    description=(
        "Production-grade prospect discovery API leveraging Google Gemini and Tavily Search. "
        "Strictly adheres to Zero Fabrication (never invents names or URLs), "
        "Security First (strict SSRF protection, secret isolation, rate limiting), "
        "and multi-platform verification across LinkedIn, X, YouTube, Instagram, "
        "WhatsApp, Facebook, Google, Email, and Threads."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for cross-origin frontend integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Standard ASGI middleware or handlers



HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle request validation errors cleanly without exposing internal details."""
    logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        errors.append(f"{loc}: {err.get('msg', 'Invalid input')}")
    return JSONResponse(
        status_code=HTTP_422,
        content={"detail": "Request validation failed", "errors": errors},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Sanitize unexpected exceptions to prevent secret leaks and stack trace disclosure."""
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred while processing the prospect discovery request."},
    )


@app.get(
    "/health",
    summary="Health check and service status",
    tags=["System"],
)
async def health_check() -> dict[str, Any]:
    """Return health status, cache performance, and configuration readiness."""
    query_cache_stats = await query_intent_cache.stats()
    search_cache_stats = await search_response_cache.stats()
    llm_metrics = llm_service.get_token_metrics()

    return {
        "status": "healthy",
        "environment": settings.environment,
        "services": {
            "gemini_configured": settings.has_gemini_key,
            "tavily_configured": settings.has_tavily_key,
        },
        "llm_metrics": llm_metrics,
        "caches": {
            "query_intent_cache": query_cache_stats,
            "search_response_cache": search_cache_stats,
        },
    }


@app.post(
    "/prospect-discovery",
    response_model=DiscoveryResponse,
    summary="Discover verified multi-platform prospects",
    description=(
        "Executes dynamic natural language prospect discovery across 9 supported platforms. "
        "Strict Zero-Fabrication guarantee: all returned profiles, names, and links are "
        "derived from verified public search results."
    ),
    tags=["Prospect Discovery"],
    status_code=status.HTTP_200_OK,
)
async def discover_prospects(payload: DiscoveryRequest) -> DiscoveryResponse:
    """Execute prospect discovery pipeline for the given search query."""
    try:
        response = await prospect_service.discover_prospects(payload.query)
        return response
    except ValueError as e:
        logger.warning("Bad request in prospect discovery: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Error during prospect discovery pipeline: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream discovery service failed to retrieve verified prospects.",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )
