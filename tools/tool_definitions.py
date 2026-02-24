"""
Tool definitions for KYC Client Onboarding Intelligence System.

Defines the tools that agents can call. The actual implementations
are handled by the tool handlers.
"""

import time
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from constants import (
    FETCH_CACHE_MAX_SIZE,
    FETCH_CACHE_TTL_SECONDS,
    HTTP_CONNECT_TIMEOUT,
    HTTP_POOL_TIMEOUT,
    HTTP_READ_TIMEOUT,
    HTTP_WRITE_TIMEOUT,
)
from logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Shared HTTP Client — connection pooling + granular timeouts + browser UA
# =============================================================================

_WEB_FETCH_TIMEOUT = httpx.Timeout(
    connect=HTTP_CONNECT_TIMEOUT,   # 5s — fail-fast on dead sites
    read=HTTP_READ_TIMEOUT,         # 25s — generous for slow gov sites
    write=HTTP_WRITE_TIMEOUT,       # 10s
    pool=HTTP_POOL_TIMEOUT,         # 5s
)

_WEB_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_shared_client: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    """Return (and lazily create) a shared async HTTP client with connection pooling."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=_WEB_FETCH_TIMEOUT,
            follow_redirects=True,
            headers=_WEB_FETCH_HEADERS,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _shared_client


async def close_shared_client() -> None:
    """Close the shared client. Safe to call multiple times or when no client exists."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


# =============================================================================
# Fetch Cache - Reduces redundant HTTP requests across agents
# =============================================================================
_fetch_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL_SECONDS = FETCH_CACHE_TTL_SECONDS


def get_cache_stats() -> dict:
    """Get current cache statistics."""
    return {
        "cached_urls": len(_fetch_cache),
        "urls": list(_fetch_cache.keys())[:20],
    }


def clear_fetch_cache():
    """Clear the fetch cache (useful between pipeline runs)."""
    global _fetch_cache
    _fetch_cache.clear()
    logger.debug("Fetch cache cleared")


# =============================================================================
# Tool Definitions for Claude API
# =============================================================================

WEB_FETCH_TOOL = {
    "name": "web_fetch",
    "description": """Fetch content from a URL and return the text content.
    Use this to read web pages, government registries, screening databases, news articles, etc.
    Returns the main text content of the page (HTML stripped).""",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch"
            },
            "extract_prompt": {
                "type": "string",
                "description": "Optional: specific information to extract from the page"
            }
        },
        "required": ["url"]
    }
}

# WEB_SEARCH_TOOL - Handled by Claude's native web_search capability
# See agents/base.py get_tool_definitions() which adds {"type": "web_search_20250305"}

SCREENING_LIST_TOOL = {
    "name": "screening_list_lookup",
    "description": """Search the Trade.gov Consolidated Screening List for sanctions matches.
    Performs fuzzy name matching against OFAC SDN, BIS Entity List, and other US screening lists.
    Returns matches with similarity scores and list details.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of person or entity to screen"
            },
            "fuzzy": {
                "type": "boolean",
                "description": "Whether to use fuzzy matching (default: true)",
                "default": True
            }
        },
        "required": ["name"]
    }
}

# All available tools
# Note: web_search is handled by Claude's native capability, not defined here
TOOL_DEFINITIONS = {
    "web_fetch": WEB_FETCH_TOOL,
    "screening_list_lookup": SCREENING_LIST_TOOL,
}


def get_tools_for_agent(tool_names: list[str]) -> list[dict]:
    """Get tool definitions for a specific agent."""
    return [TOOL_DEFINITIONS[name] for name in tool_names if name in TOOL_DEFINITIONS]


# ============================================================================
# Tool Handlers - Execute the actual tool calls
# ============================================================================

def validate_url(url: str) -> tuple[bool, str]:
    """
    Validate and normalize a URL.

    Returns:
        Tuple of (is_valid, normalized_url_or_error_message)
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)

        if not parsed.netloc:
            return False, "URL must have a valid domain"

        if parsed.scheme not in ("http", "https"):
            return False, "URL must use http or https scheme"

        domain = parsed.netloc
        if "." not in domain and domain != "localhost":
            return False, f"Invalid domain: {domain}"

        return True, url

    except Exception as e:
        return False, f"URL parsing error: {str(e)}"


def extract_text_from_html(html_content: str, max_length: int = 30000) -> str:
    """
    Extract readable text from HTML content.

    Uses BeautifulSoup if available, falls back to regex.
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "html.parser")

        # Remove script and style elements
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()

        # Get text
        text = soup.get_text(separator=" ", strip=True)

        # Normalize whitespace
        import re
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) > max_length:
            logger.info("HTML text truncated: %d chars → %d", len(text), max_length)
            text = text[:max_length] + "... [truncated]"

        return text

    except ImportError:
        # Fallback to regex-based extraction
        logger.debug("BeautifulSoup not available, using regex fallback")
        import re
        content = html_content
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<[^>]+>', ' ', content)
        content = re.sub(r'\s+', ' ', content).strip()

        if len(content) > max_length:
            logger.info("HTML text truncated (regex): %d chars → %d", len(content), max_length)
            content = content[:max_length] + "... [truncated]"

        return content


async def handle_web_fetch(url: str, extract_prompt: str = None) -> dict:
    """
    Fetch a URL and return its content.
    """
    # Validate URL
    is_valid, result = validate_url(url)
    if not is_valid:
        logger.warning(f"Invalid URL rejected: {url} - {result}")
        return {
            "success": False,
            "url": url,
            "error": f"Invalid URL: {result}"
        }

    validated_url = result

    # Check cache first
    cache_key = validated_url.lower().rstrip('/')
    if cache_key in _fetch_cache:
        cached_result, cached_at = _fetch_cache[cache_key]
        if time.time() - cached_at < CACHE_TTL_SECONDS:
            logger.info(f"Cache hit for {validated_url}")
            return {**cached_result.copy(), "from_cache": True}
        else:
            del _fetch_cache[cache_key]

    logger.debug(f"Fetching URL: {validated_url}")

    try:
        client = _get_shared_client()
        response = await client.get(validated_url)
        response.raise_for_status()

        content = extract_text_from_html(response.text)

        logger.debug(f"Successfully fetched {validated_url} - {len(content)} chars")

        result = {
            "success": True,
            "url": str(response.url),
            "status_code": response.status_code,
            "content": content
        }

        # Cache successful results (with size limit)
        if len(_fetch_cache) >= FETCH_CACHE_MAX_SIZE:
            # Evict oldest entry
            oldest_key = min(_fetch_cache, key=lambda k: _fetch_cache[k][1])
            del _fetch_cache[oldest_key]
        _fetch_cache[cache_key] = (result, time.time())

        return result

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code}: {e.response.reason_phrase}"
        logger.warning(f"HTTP error fetching {validated_url}: {error_msg}")
        return {"success": False, "url": validated_url, "error": error_msg}

    except httpx.ConnectTimeout:
        logger.warning(f"Connect timeout fetching {validated_url} — site may be down")
        return {"success": False, "url": validated_url, "error": "Connection timed out — site may be down or unreachable"}

    except httpx.ReadTimeout:
        logger.warning(f"Read timeout fetching {validated_url} — site too slow")
        return {"success": False, "url": validated_url, "error": "Read timed out — site responded but is too slow"}

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching {validated_url}")
        return {"success": False, "url": validated_url, "error": "Request timed out"}

    except httpx.RequestError as e:
        logger.warning(f"Request error fetching {validated_url}: {str(e)}")
        return {"success": False, "url": validated_url, "error": f"Request failed: {str(e)}"}

    except Exception as e:
        logger.exception(f"Unexpected error fetching {validated_url}")
        return {"success": False, "url": validated_url, "error": f"Unexpected error: {str(e)}"}


async def handle_screening_list_lookup(name: str, fuzzy: bool = True) -> dict:
    """Handle screening list lookup tool call."""
    from tools.screening_list import search_screening_list
    return await search_screening_list(name, fuzzy=fuzzy)


# Tool handler registry
TOOL_HANDLERS: dict[str, Callable] = {
    "web_fetch": handle_web_fetch,
    "screening_list_lookup": handle_screening_list_lookup,
}


async def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """Execute a tool and return the result."""
    if tool_name not in TOOL_HANDLERS:
        return {"error": f"Unknown tool: {tool_name}"}

    handler = TOOL_HANDLERS[tool_name]
    return await handler(**tool_input)


def get_tool_handler(tool_name: str) -> Callable | None:
    """Get the handler function for a tool."""
    return TOOL_HANDLERS.get(tool_name)
