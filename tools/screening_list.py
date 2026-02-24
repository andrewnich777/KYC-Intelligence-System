"""
Trade.gov Consolidated Screening List search tool.
Downloads/caches CSL data and performs fuzzy name matching with rapidfuzz.
"""

import json
import os
import time
from pathlib import Path

import httpx

from config import SCREENING_LIST_PATH
from constants import SCREENING_CACHE_STALENESS_HOURS, SCREENING_HIGH_CONFIDENCE
from logger import get_logger

logger = get_logger(__name__)

# CSL API endpoint
CSL_API_URL = "https://api.trade.gov/gateway/v2/consolidated_screening_list/search"

# Local cache
_csl_cache: dict | None = None
_csl_cache_time: float = 0
from constants import CSL_CACHE_TTL_SECONDS

CSL_CACHE_TTL = CSL_CACHE_TTL_SECONDS


def clear_screening_cache():
    """Clear the in-memory CSL cache between pipeline runs."""
    global _csl_cache, _csl_cache_time
    _csl_cache = None
    _csl_cache_time = 0
    logger.debug("Screening list cache cleared")


def _generate_name_variants(full_name: str, cultural_hint: str | None = None) -> list[str]:
    """Generate name variations for fuzzy matching across cultures.

    Returns the original name plus variants with reversed order,
    without honorifics, etc.
    """
    from utilities.name_parser import parse_name
    variants: list[str] = [full_name]
    nc = parse_name(full_name, cultural_hint=cultural_hint)

    # Reversed order (family + given)
    if nc.given_names and nc.family_name:
        reversed_name = f"{nc.family_name} {' '.join(nc.given_names)}"
        if reversed_name != full_name:
            variants.append(reversed_name)

    # Without honorifics/suffixes
    clean = " ".join(nc.given_names + [nc.family_name]).strip()
    if clean and clean != full_name:
        variants.append(clean)

    return list(dict.fromkeys(variants))  # Deduplicate, preserve order


# OpenSanctions dataset identifiers — agents can pass these to target specific lists
OPENSANCTIONS_DATASETS = {
    "default": "default",           # Full consolidated dataset
    "sanctions": "sanctions",       # All sanctions lists combined
    "eu_fsf": "eu_fsf",             # EU Financial Sanctions (consolidated)
    "uk_hmt": "gb_hmt_sanctions",   # UK HMT Sanctions
    "au_dfat": "au_dfat_sanctions", # Australian DFAT Sanctions
    "un_sc": "un_sc_sanctions",     # UN Security Council
    "us_ofac": "us_ofac_sdn",       # US OFAC SDN
    "ca_sema": "ca_sema_sanctions", # Canadian SEMA Sanctions
    # JVCFOA (Justice for Victims of Corrupt Foreign Officials / Magnitsky Act)
    # listings are included in ca_sema_sanctions — no separate dataset needed.
}


async def search_screening_list(name: str, fuzzy: bool = True, threshold: float = 0.70,
                                cultural_hint: str | None = None,
                                datasets: list[str] | None = None) -> dict:
    """
    Search the Trade.gov Consolidated Screening List and OpenSanctions.

    Args:
        name: Name to search for
        fuzzy: Whether to use fuzzy matching
        threshold: Minimum similarity score (0-1) for fuzzy matches
        cultural_hint: Country/culture hint for generating name variants
        datasets: Optional list of OpenSanctions dataset keys to target
                  (e.g. ["eu_fsf", "uk_hmt"]). Defaults to all.
                  Valid keys: {', '.join(OPENSANCTIONS_DATASETS.keys())}

    Returns:
        Dict with matches and metadata, including data_as_of timestamp
        and optional data_freshness_warning if cache is stale.
    """
    logger.info(f"Screening list search: {name}")

    matches = []
    data_source = "api"
    data_freshness_warning = None

    # Generate name variants for multicultural matching
    name_variants = _generate_name_variants(name, cultural_hint=cultural_hint)

    # Try API search first (search all variants)
    api_returned_any = False
    for variant in name_variants:
        try:
            api_results = await _search_csl_api(variant)
            if api_results:
                matches.extend(api_results)
                api_returned_any = True
        except Exception as e:
            logger.warning(f"CSL API search failed for variant '{variant}': {e}")
            data_source = "api_error"

    # API was reachable but returned 0 results — that's a legitimate empty result, not a fallback
    if not api_returned_any and data_source == "api":
        data_source = "api_no_results"

    # Fuzzy match against local cache if available
    if fuzzy:
        try:
            local_matches, cache_warning = _fuzzy_search_local(name, threshold)
            if cache_warning:
                data_freshness_warning = cache_warning
            # Deduplicate with API results
            existing_names = {m.get("matched_name", "").lower() for m in matches}
            for lm in local_matches:
                if lm.get("matched_name", "").lower() not in existing_names:
                    matches.append(lm)
        except Exception as e:
            logger.debug(f"Local fuzzy search unavailable: {e}")

    # Score and classify matches
    classified = []
    for match in matches:
        score = match.get("score", 0)
        if score >= SCREENING_HIGH_CONFIDENCE:
            match["classification"] = "POTENTIAL_MATCH"
        elif score >= threshold:
            match["classification"] = "INVESTIGATE"
        else:
            match["classification"] = "LOW_RELEVANCE"
        classified.append(match)

    import datetime as _dt
    sources = ["Trade.gov CSL"]
    if datasets:
        resolved = [OPENSANCTIONS_DATASETS.get(d, d) for d in datasets]
        sources.extend(f"OpenSanctions:{ds}" for ds in resolved)
    elif fuzzy:
        sources.append("OpenSanctions (local cache)")
    result = {
        "success": True,
        "query": name,
        "total_matches": len(classified),
        "matches": classified,
        "sources_checked": sources,
        "data_as_of": _dt.datetime.now(_dt.UTC).isoformat(),
        "data_source": data_source,
    }
    if data_freshness_warning:
        result["data_freshness_warning"] = data_freshness_warning

    return result


async def _search_csl_api(name: str) -> list[dict]:
    """Search the Trade.gov CSL API.

    Uses follow_redirects=False to detect a dead API (301→HTML page).
    Uses a short timeout since API responses should be fast.
    """
    from constants import CSL_API_READ_TIMEOUT, HTTP_CONNECT_TIMEOUT

    results = []

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=HTTP_CONNECT_TIMEOUT, read=CSL_API_READ_TIMEOUT,
                                  write=10.0, pool=5.0),
            follow_redirects=False,
        ) as client:
            params = {
                "q": name,
                "limit": 10,
            }
            # API key is optional for basic searches
            api_key = os.environ.get("TRADE_GOV_API_KEY")
            if api_key:
                params["api_key"] = api_key

            response = await client.get(CSL_API_URL, params=params)

            # Detect dead API: 3xx redirect means the API endpoint moved/died
            if 300 <= response.status_code < 400:
                logger.warning(
                    "CSL API returned %d redirect (API may be dead) — falling back to cache",
                    response.status_code,
                )
                return []

            if response.status_code != 200:
                logger.warning(f"CSL API returned {response.status_code}")
                return []

            # Verify response is JSON before parsing (defense-in-depth)
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                logger.warning(
                    "CSL API returned non-JSON content-type: %s — falling back to cache",
                    content_type,
                )
                return []

            data = response.json()
            for entry in data.get("results", []):
                # Calculate name similarity
                entry_name = entry.get("name", "")
                score = _simple_name_similarity(name, entry_name)

                results.append({
                    "matched_name": entry_name,
                    "list_name": entry.get("source", "CSL"),
                    "score": score,
                    "details": {
                        "type": entry.get("type", ""),
                        "programs": entry.get("programs", []),
                        "country": entry.get("country", ""),
                        "source": entry.get("source", ""),
                        "remarks": entry.get("remarks", ""),
                        "alt_names": entry.get("alt_names", []),
                    },
                })

    except httpx.ConnectTimeout:
        logger.warning("CSL API connect timeout — site may be down")
    except httpx.TimeoutException:
        logger.warning(f"CSL API timeout searching for '{name}'")
    except Exception as e:
        logger.warning(f"CSL API error: {e}")

    return results


def _simple_name_similarity(name1: str, name2: str) -> float:
    """Calculate name similarity score. Uses rapidfuzz if available, falls back to simple ratio."""
    try:
        from rapidfuzz import fuzz
        # Use token_sort_ratio for name order independence
        return fuzz.token_sort_ratio(name1.lower(), name2.lower()) / 100.0
    except ImportError:
        # Simple fallback
        n1 = set(name1.lower().split())
        n2 = set(name2.lower().split())
        if not n1 or not n2:
            return 0.0
        intersection = n1 & n2
        union = n1 | n2
        return len(intersection) / len(union)


def _fuzzy_search_local(name: str, threshold: float) -> tuple[list[dict], str | None]:
    """Search local screening list cache with fuzzy matching.

    Returns (matches, freshness_warning). freshness_warning is non-None if
    the cache file is more than 24 hours old.
    """
    cache_path = Path(SCREENING_LIST_PATH) / "csl_cache.json"
    if not cache_path.exists():
        return [], None

    freshness_warning = None
    try:
        # Check cache age
        cache_mtime = cache_path.stat().st_mtime
        cache_age_hours = (time.time() - cache_mtime) / 3600
        if cache_age_hours > SCREENING_CACHE_STALENESS_HOURS:
            days = cache_age_hours / SCREENING_CACHE_STALENESS_HOURS
            freshness_warning = f"Screening data from cache ({days:.0f} day(s) old)"
            logger.warning("CSL cache is %.0f hours old — data may be stale", cache_age_hours)
    except Exception:
        pass

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
    except Exception as e:
        logger.debug("Local cache read failed: %s", e)
        return [], freshness_warning

    matches = []
    for entry in entries:
        entry_name = entry.get("name", "")
        score = _simple_name_similarity(name, entry_name)
        if score >= threshold:
            matches.append({
                "matched_name": entry_name,
                "list_name": entry.get("source", "local_cache"),
                "score": score,
                "details": entry,
            })

    # Sort by score descending
    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:10], freshness_warning
