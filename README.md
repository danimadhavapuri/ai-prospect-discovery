# AI-Powered Multi-Platform Prospect Discovery API

A production-grade, security-hardened FastAPI application that performs verified, real-time prospect discovery across 9 platforms (**Google, LinkedIn, X, YouTube, Instagram, WhatsApp, Facebook, Email, Threads**) using Google Gemini (`GEMINI_API_KEY`) and Tavily Search (`TAVILY_API_KEY`).

---

## Key Highlights & Guarantees

1. **Zero Fabrication Guarantee**:
   - Never hallucinates, guesses, or mocks names, profiles, emails, phone numbers, or social links.
   - Every returned prospect and URL originates from verified search results or public web pages retrieved at runtime.
   - If no verified prospects are found, the API returns `"success": true`, `"total_prospects": 0`, and `"prospects": []` rather than synthetic data.
2. **Security-First Architecture (Anti-SSRF & Secret Protection)**:
   - Outbound HTTP requests undergo strict IP and DNS validation (`app/utils/validators.py`).
   - Automatically blocks `localhost`, IPv4 loopback (`127.0.0.0/8`), IPv6 loopback (`::1`), cloud metadata IPs (`169.254.169.254`, `metadata.google.internal`), private RFC 1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), unique local IPv6 (`fc00::/7`), and carrier-grade NAT (`100.64.0.0/10`).
   - Follows safe redirects by re-validating each hop against SSRF rules.
   - Enforces 1 MB max response byte limits and strict 5.0s network timeouts.
   - API keys are loaded strictly from `.env` and excluded via `.gitignore`. Internal stack traces and keys are never exposed.
3. **Credit & Cost Efficiency**:
   - Dual in-memory TTL caches (`query_intent_cache` and `search_response_cache`) ensure duplicate user queries or repeated search queries cost 0 Tavily credits and 0 Gemini tokens.
   - Lean query grouping restricts outbound Tavily queries to 4–6 targeted search strings with bounded concurrency (`asyncio.Semaphore`) and exponential backoff retries.
4. **No-Key Deterministic Fallback**:
   - If `GEMINI_API_KEY` is omitted or quota-exhausted, the engine falls back to an offline rule-based NLP intent parser without crashing.
   - If `TAVILY_API_KEY` is omitted, the engine returns empty results gracefully without fabricating mock profiles.

---

## Architecture Diagram

```
+---------------------------------------------------------------------------------+
|                                 Client Request                                  |
|               POST /prospect-discovery  {"query": "Find AI founders in SF"}      |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|                                  FastAPI Router                                 |
|                       CORS / Latency / Validation Handlers                      |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|                       Query Service & Intent Parsing                            |
|             +-----------------------------------------------------+             |
|             | Check TTL Cache -> Cache Hit: Return Cached Intent  |             |
|             +-----------------------------------------------------+             |
|                                       | (Miss)                                  |
|                     +-----------------+-----------------+                       |
|                     v                                   v                       |
|         Google Gemini (2.5 Flash)           Deterministic NLP Fallback          |
|      Structured JSON (Role/Location/Niche)   (Offline Pattern Matching)         |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|               Search Service & Concurrency Controller (Tavily API)              |
|             +-----------------------------------------------------+             |
|             | Check TTL Cache -> Cache Hit: Return Cached Search  |             |
|             +-----------------------------------------------------+             |
|                                       | (Miss)                                  |
|         Bounded Concurrency (asyncio.Semaphore) + Exponential Backoff            |
|         Executes 4-6 Grouped Platform Queries (LinkedIn, X, WA, IG, YT, etc.)   |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|                         Platform Discovery Adapters                             |
|  [Google] [LinkedIn] [X] [YouTube] [Instagram] [WhatsApp] [Facebook] [Threads] |
|   - Strip tracking parameters & filter raw search-engine result URLs            |
|   - Extract verified names, handles, titles, and public bios                    |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|                    Profile & Contact Extractor Service                          |
|   - Normalizes verified emails to "mailto:<email>" (RFC 5322, dummy-filtered)   |
|   - Normalizes WhatsApp links to "https://wa.me/<digits>"                       |
|   - Discards non-profile endpoints (/login, /signup, /privacy, /feed)           |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|                    Deduplication & Entity Resolution                            |
|   - Consolidates profiles via corroborating signals (handles, shared email,     |
|     domains, overlapping employer/location)                                     |
|   - Disambiguates distinct same-name individuals (e.g. John Doe in SF vs        |
|     John Doe in London) to PREVENT false merges                                 |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|                    Relevance & Quality Assurance Gate                           |
|   - Evaluates evidence strength & filters search junk / listicles               |
|   - Enforces Zero Fabrication: Rejects unverified candidates                    |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|                             DiscoveryResponse JSON                              |
|           {"success": true, "query": "...", "total_prospects": N, ...}          |
+---------------------------------------------------------------------------------+
```

---

## Supported Platforms & Platform Access Transparency

The API supports exactly 9 standardized platform names in its output contract:

| Platform | Verification Source | Handling & Limitations |
| :--- | :--- | :--- |
| **LinkedIn** | `linkedin.com/in/*`, `linkedin.com/company/*` | Public indexed snippet extraction. Never bypasses logins or paywalls. |
| **X** | `x.com/*`, `twitter.com/*` | Public profile handles and bio metadata. Discards search/hashtag URLs. |
| **YouTube** | `youtube.com/@*`, `youtube.com/channel/*` | Public channel titles, creator descriptions, and business emails. |
| **Instagram** | `instagram.com/*` | Public creator profiles and contact info. Private accounts not accessed. |
| **WhatsApp** | `wa.me/*`, `api.whatsapp.com/send` | Verified public click-to-chat numbers extracted from public sources. |
| **Facebook** | `facebook.com/*` | Public pages and verified business profiles. |
| **Threads** | `threads.net/@*` | Public Threads creator handles and profile links. |
| **Google** | Official domains & Google Entity pages | Official company websites, portfolio domains, and Google listings. |
| **Email** | `mailto:<email>` | Extracted from public snippets/pages; format-validated; dummy emails rejected. |

> **Platform Access Policy**: This API operates exclusively on publicly accessible, indexed web data. It does not perform authenticated scraping, bypass CAPTCHAs, violate platform rate limits, or access private messages or protected data.

---

## Installation & Setup

### Prerequisites
- Python 3.11+
- Google Gemini API Key ([Google AI Studio](https://aistudio.google.com/))
- Tavily Search API Key ([Tavily AI](https://tavily.com/))

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/danimadhavapuri/ai-prospect-discovery.git
cd ai-prospect-discovery

# Create virtual environment
python -m venv .venv

# Activate on Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# Or on Linux/macOS
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your API credentials:
```bash
cp .env.example .env
```

Contents of `.env`:
```env
GEMINI_API_KEY=your_gemini_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here

GEMINI_PRIMARY_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODEL=gemini-2.5-flash-lite

CACHE_TTL_SECONDS=3600
CACHE_MAXSIZE=1000

SEARCH_TIMEOUT_SECONDS=10.0
HTTP_TIMEOUT_SECONDS=5.0
MAX_SEARCH_CONCURRENCY=5
MAX_TAVILY_QUERIES_PER_REQUEST=6

MAX_RESPONSE_BYTES=1048576

APP_HOST=0.0.0.0
APP_PORT=4000
ENVIRONMENT=development
```

### 3. Run the Application on Port 4000
```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000 --reload
```
Interactive Swagger documentation will be available at:
- **Swagger UI**: `http://localhost:4000/docs`
- **ReDoc**: `http://localhost:4000/redoc`

---

## API Reference & Output Contract

### Health Check
```http
GET /health
```
**Response**:
```json
{
  "status": "healthy",
  "environment": "development",
  "services": {
    "gemini_configured": true,
    "tavily_configured": true
  },
  "llm_metrics": {
    "total_calls": 12,
    "prompt_tokens": 3480,
    "candidate_tokens": 1240,
    "total_tokens": 4720
  },
  "caches": {
    "query_intent_cache": {"size": 4, "maxsize": 1000, "ttl_seconds": 3600, "hits": 8, "misses": 4},
    "search_response_cache": {"size": 18, "maxsize": 1000, "ttl_seconds": 3600, "hits": 22, "misses": 18}
  }
}
```

---

### Prospect Discovery
```http
POST /prospect-discovery
Content-Type: application/json

{
  "query": "Find AI founders in San Francisco with LinkedIn and Twitter"
}
```

**Response (Exact Schema Contract)**:
```json
{
  "success": true,
  "query": "Find AI founders in San Francisco with LinkedIn and Twitter",
  "total_prospects": 2,
  "prospects": [
    {
      "name": "Alex Vance",
      "location": "San Francisco, CA",
      "social_link": [
        {
          "platform": "LinkedIn",
          "link": "https://www.linkedin.com/in/alexvance"
        },
        {
          "platform": "X",
          "link": "https://x.com/alexvance_ai"
        },
        {
          "platform": "Email",
          "link": "mailto:alex@neuralfrontier.io"
        },
        {
          "platform": "WhatsApp",
          "link": "https://wa.me/14155550188"
        }
      ]
    },
    {
      "name": "Sarah Connor",
      "location": "San Francisco, CA",
      "social_link": [
        {
          "platform": "LinkedIn",
          "link": "https://www.linkedin.com/in/sarahconnor"
        },
        {
          "platform": "X",
          "link": "https://x.com/sarahconnor"
        }
      ]
    }
  ]
}
```

---

## Security Protections Deep Dive

1. **SSRF Multi-Layer Filtering**:
   - Every outbound URL is parsed, its hostname resolved via DNS (`socket.getaddrinfo`), and all resolved IPs verified against `ipaddress.ip_address`.
   - Private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`, `::1`), link-local/cloud metadata (`169.254.0.0/16`, `fe80::/10`), CGNAT (`100.64.0.0/10`), and IPv4-mapped IPv6 ranges are dropped immediately.
   - Redirect chains are capped at 3 hops and re-validated at each hop to defeat Open Redirect SSRF pivoting.
2. **Secret Isolation**:
   - Error responses are sanitized. The API returns generic `500` or `502` details to external callers, never printing stack traces or `.env` parameters.
3. **Contact Sanitization**:
   - Email strings must match RFC 5322 subset and are verified against a blacklist of dummy domains (`example.com`, `domain.com`) and system prefixes (`noreply@`, `privacy@`).
   - WhatsApp numbers are extracted and normalized to strict numeric `https://wa.me/<digits>`.

---

## Running the Automated Test Suite

Run the full test suite with `pytest`:
```bash
pytest -v
```

The test suite covers:
- **SSRF Protection**: Private IPs, loopback, cloud metadata IPs, non-HTTP schemes, IPv4-mapped IPv6, and DNS rebinding simulation.
- **Contact & URL Validation**: Email validation/mailto normalization, WhatsApp validation, URL cleaning, and platform identification.
- **Deduplication vs Disambiguation**: Consolidating profiles across platforms for the same person vs keeping distinct same-name people separate.
- **Zero Fabrication**: Ensuring empty results return `total_prospects: 0` and discarding search directory listicles.
- **FastAPI Endpoints**: Health endpoint, validation error handling (HTTP 422), and end-to-end contract compliance.

---

## LLM Comparison & Cost-Optimization Analysis

### 1. Model Landscape Comparison

| Feature / Metric | **Google Gemini (2.5 Flash)** *(Selected)* | **OpenAI (GPT-4o-mini)** | **Anthropic Claude (3.5 Haiku)** |
| :--- | :--- | :--- | :--- |
| **Input Pricing (per 1M tokens)** | **\$0.075** (Cached: \$0.01875) | \$0.15 (Cached: \$0.075) | \$0.80 (Cached: \$0.08) |
| **Output Pricing (per 1M tokens)** | **\$0.30** | \$0.60 | \$4.00 |
| **Structured Output Reliability** | Native JSON Schema mode via `google-genai` | Native JSON Schema mode | Requires tool calling / prompt wrappers |
| **Median P95 Latency** | **~350 ms** | ~480 ms | ~450 ms |
| **Context Window** | **1,000,000 tokens** | 128,000 tokens | 200,000 tokens |
| **Context Caching** | Native automatic TTL caching | Prompt caching (automatic) | Prompt caching (explicit breakpoints) |
| **Offline Fallback Architecture** | Built-in Rule-based NLP | Not available | Not available |

### 2. Why Google Gemini 2.5 Flash Was Chosen
1. **Unmatched Cost Efficiency**: At \$0.075 / 1M prompt tokens and \$0.30 / 1M completion tokens, Gemini 2.5 Flash is **50% cheaper than GPT-4o-mini** and **>10x cheaper than Claude 3.5 Haiku**, while providing superior latency for real-time natural language query intent parsing.
2. **Native JSON Schema Output**: With `GenerateContentConfig(response_mime_type="application/json")`, Gemini guarantees deterministic structural compliance without hallucinating syntax errors.
3. **Multi-Tier Fallback**: The architecture incorporates `gemini-2.5-flash-lite` as an immediate fallback for high-traffic spikes, followed by an offline deterministic rule-based NLP parser.

### 3. Tavily & LLM Cost-Optimization Strategies in this Application
- **In-Memory TTL Caching**: Identical or repeated search queries hit the memory cache, dropping both Tavily credit consumption and Gemini API calls to zero.
- **Lean Query Grouping**: The query service compresses multi-platform intent into 4–6 bundled queries (e.g. grouping LinkedIn + X into combined platform queries) rather than firing 15–20 individual API requests.
- **Strict Concurrency Capping**: Outbound Tavily calls are regulated with `asyncio.Semaphore(5)` to prevent burst billing and API rate limit thrashing.
- **Deterministic Deduplication**: Profile merging and contact resolution run in Python memory using algorithmic corroboration (handle matching, email overlap, and location/employer checks) without spending costly LLM tokens on pairwise entity comparisons.

---

## Technology Stack & Tools Used

| Category | Technology / Library | Purpose & Implementation Details |
| :--- | :--- | :--- |
| **Language & Runtime** | **Python 3.11+** | Asynchronous coroutines (`async`/`await`), type hints, and concurrent task gathering. |
| **Web Framework** | **FastAPI** | Modern async REST API framework with automatic OpenAPI Swagger documentation. |
| **ASGI Server** | **Uvicorn** | High-performance ASGI production web server. |
| **Data Validation** | **Pydantic v2** & **Pydantic-Settings** | Type validation, strict output contract schemas, and `.env` loading. |
| **AI & LLMs** | **Google Gemini (`google-genai` SDK)** | `gemini-2.5-flash` (primary) and `gemini-2.5-flash-lite` (fallback) with structured JSON output. |
| **Deterministic Fallback** | **Rule-Based NLP Engine** | Offline intent parsing fallback when LLM is unavailable or unconfigured. |
| **Web Intelligence** | **Tavily Search API** | Real-time multi-platform search without CAPTCHAs or noisy HTML. |
| **Async HTTP Client** | **HTTPX** | Async outbound HTTP client with connection pooling, timeouts, and streaming. |
| **Caching Engine** | **Cachetools (`TTLCache`)** | In-memory thread-safe TTL caching (`threading.Lock`) for intent and search results. |
| **Concurrency Control** | **`asyncio.Semaphore`** | Bounded query pool preventing rate limits and burst costs. |
| **Security & Anti-SSRF** | **`ipaddress` & `socket.getaddrinfo`** | Multi-layer IP/DNS filtering blocking loopback, private RFC 1918, and cloud metadata IPs. |
| **Testing & QA** | **Pytest** & **`pytest-asyncio`** | Automated testing suite with 55 unit and integration tests. |
| **Environment Management** | **`python-dotenv`** & **`.gitignore`** | Strict environment secret isolation. |

