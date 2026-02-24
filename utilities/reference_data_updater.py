"""
Live reference data updater.

Fetches current FATF, OFAC, and FINTRAC lists from official sources,
computes diffs against the static lists in reference_data.py, and optionally
writes override files that reference_data.py loads at startup.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from constants import HTTP_CONNECT_TIMEOUT, HTTP_POOL_TIMEOUT, HTTP_READ_TIMEOUT, HTTP_WRITE_TIMEOUT

logger = logging.getLogger(__name__)

_UPDATER_TIMEOUT = httpx.Timeout(
    connect=HTTP_CONNECT_TIMEOUT,
    read=HTTP_READ_TIMEOUT,
    write=HTTP_WRITE_TIMEOUT,
    pool=HTTP_POOL_TIMEOUT,
)

_UPDATER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_SCREENING_LISTS_DIR = Path(__file__).parent.parent / "screening_lists"


# =============================================================================
# Diff Computation
# =============================================================================

@dataclass
class ListDiff:
    """Difference between current and fetched versions of a reference list."""
    list_name: str
    current: list[str] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @classmethod
    def compute(cls, list_name: str, current: list[str], fetched: list[str]) -> "ListDiff":
        """Compute added/removed between two lists (case-insensitive)."""
        current_set = {c.lower() for c in current}
        fetched_set = {f.lower() for f in fetched}

        # Preserve original casing from the fetched list
        fetched_map = {f.lower(): f for f in fetched}
        current_map = {c.lower(): c for c in current}

        added = [fetched_map[k] for k in (fetched_set - current_set)]
        removed = [current_map[k] for k in (current_set - fetched_set)]

        return cls(
            list_name=list_name,
            current=current,
            fetched=fetched,
            added=sorted(added),
            removed=sorted(removed),
        )

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed)


@dataclass
class UpdateReport:
    """Collects all diffs and formats a human-readable report."""
    diffs: list[ListDiff] = field(default_factory=list)
    fetch_errors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def has_changes(self) -> bool:
        return any(d.has_changes for d in self.diffs)

    def format_text(self) -> str:
        """Format a human-readable text report."""
        lines = [
            f"Reference Data Update Report — {self.timestamp.isoformat()}",
            "=" * 60,
        ]

        if self.fetch_errors:
            lines.append("\nFetch Errors:")
            for err in self.fetch_errors:
                lines.append(f"  - {err}")

        if not self.has_changes:
            lines.append("\nNo changes detected. All lists are up to date.")
            return "\n".join(lines)

        for diff in self.diffs:
            if not diff.has_changes:
                lines.append(f"\n{diff.list_name}: No changes")
                continue

            lines.append(f"\n{diff.list_name}:")
            if diff.added:
                lines.append(f"  Added ({len(diff.added)}):")
                for item in diff.added:
                    lines.append(f"    + {item}")
            if diff.removed:
                lines.append(f"  Removed ({len(diff.removed)}):")
                for item in diff.removed:
                    lines.append(f"    - {item}")

        return "\n".join(lines)


# =============================================================================
# Fetchers (async web scraping)
# =============================================================================

async def fetch_fatf_lists() -> tuple[list[str], list[str]]:
    """Fetch current FATF grey and black lists.

    Returns:
        Tuple of (grey_list, black_list).
    """
    grey_list = []
    black_list = []

    try:
        async with httpx.AsyncClient(timeout=_UPDATER_TIMEOUT, follow_redirects=True, headers=_UPDATER_HEADERS) as client:
            # FATF grey list page
            resp = await client.get("https://www.fatf-gafi.org/en/countries/black-and-grey-lists.html")
            if resp.status_code == 200:
                text = resp.text
                # Parse the page for country names (simplified scraping)
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(text, "html.parser")
                    # Look for jurisdiction lists in the page content
                    for section in soup.find_all(["h2", "h3"]):
                        heading_text = section.get_text(strip=True).lower()
                        if "increased monitoring" in heading_text or "grey" in heading_text:
                            # Gather country names from the next sibling list
                            sibling = section.find_next(["ul", "ol", "div"])
                            if sibling:
                                for li in sibling.find_all("li"):
                                    name = li.get_text(strip=True)
                                    if name and len(name) < 100:
                                        grey_list.append(name)
                        elif "call for action" in heading_text or "black" in heading_text:
                            sibling = section.find_next(["ul", "ol", "div"])
                            if sibling:
                                for li in sibling.find_all("li"):
                                    name = li.get_text(strip=True)
                                    if name and len(name) < 100:
                                        black_list.append(name)
                except ImportError:
                    logger.warning("beautifulsoup4 required for FATF list parsing")
            else:
                logger.warning("FATF page returned status %d", resp.status_code)
    except Exception as e:
        logger.error("Failed to fetch FATF lists: %s", e)

    return grey_list, black_list


async def fetch_ofac_programs() -> list[str]:
    """Fetch current OFAC sanctioned countries/programs."""
    countries = []
    try:
        async with httpx.AsyncClient(timeout=_UPDATER_TIMEOUT, follow_redirects=True, headers=_UPDATER_HEADERS) as client:
            resp = await client.get("https://sanctionssearch.ofac.treas.gov/")
            if resp.status_code == 200:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Look for program/country options in dropdown
                    for option in soup.find_all("option"):
                        val = option.get_text(strip=True)
                        if val and val not in ("", "All", "Select"):
                            countries.append(val)
                except ImportError:
                    pass
    except Exception as e:
        logger.error("Failed to fetch OFAC programs: %s", e)

    return countries


async def fetch_fintrac_countries() -> list[str]:
    """Fetch countries with FINTRAC countermeasure directives."""
    countries = []
    try:
        async with httpx.AsyncClient(timeout=_UPDATER_TIMEOUT, follow_redirects=True, headers=_UPDATER_HEADERS) as client:
            resp = await client.get("https://fintrac-canafe.canada.ca/guidance-directives/overview-apercu/FATF-GAFI-eng")
            if resp.status_code == 200:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for li in soup.find_all("li"):
                        text = li.get_text(strip=True)
                        if "countermeasures" in text.lower():
                            # Extract country name before the keyword
                            parts = text.split("–")
                            if len(parts) >= 1:
                                countries.append(parts[0].strip())
                except ImportError:
                    pass
    except Exception as e:
        logger.error("Failed to fetch FINTRAC countries: %s", e)

    return countries


# =============================================================================
# Update Orchestration
# =============================================================================

async def check_for_updates() -> UpdateReport:
    """Fetch all reference data sources and compute diffs against current static lists."""
    from utilities.reference_data import (
        FATF_BLACK_LIST,
        FATF_GREY_LIST,
        FINTRAC_HIGH_RISK_COUNTRIES,
        OFAC_SANCTIONED_COUNTRIES,
    )

    report = UpdateReport()

    # Fetch FATF lists
    try:
        fetched_grey, fetched_black = await fetch_fatf_lists()
        if fetched_grey:
            report.diffs.append(ListDiff.compute("FATF Grey List", FATF_GREY_LIST, fetched_grey))
        else:
            report.fetch_errors.append("Could not fetch FATF grey list")
        if fetched_black:
            report.diffs.append(ListDiff.compute("FATF Black List", FATF_BLACK_LIST, fetched_black))
        else:
            report.fetch_errors.append("Could not fetch FATF black list")
    except Exception as e:
        report.fetch_errors.append(f"FATF fetch error: {e}")

    # Fetch OFAC
    try:
        fetched_ofac = await fetch_ofac_programs()
        if fetched_ofac:
            report.diffs.append(ListDiff.compute("OFAC Sanctioned Countries", OFAC_SANCTIONED_COUNTRIES, fetched_ofac))
        else:
            report.fetch_errors.append("Could not fetch OFAC programs")
    except Exception as e:
        report.fetch_errors.append(f"OFAC fetch error: {e}")

    # Fetch FINTRAC
    try:
        fetched_fintrac = await fetch_fintrac_countries()
        if fetched_fintrac:
            report.diffs.append(
                ListDiff.compute("FINTRAC High-Risk Countries", FINTRAC_HIGH_RISK_COUNTRIES, fetched_fintrac)
            )
        else:
            report.fetch_errors.append("Could not fetch FINTRAC countries")
    except Exception as e:
        report.fetch_errors.append(f"FINTRAC fetch error: {e}")

    return report


def apply_updates(report: UpdateReport) -> Path:
    """Write override JSON and append to audit log.

    Returns the path to the override file.
    """
    _SCREENING_LISTS_DIR.mkdir(parents=True, exist_ok=True)

    override_path = _SCREENING_LISTS_DIR / "reference_data_override.json"
    audit_path = _SCREENING_LISTS_DIR / "update_audit.jsonl"

    # Build override data from diffs
    overrides = {}
    for diff in report.diffs:
        if diff.has_changes:
            overrides[diff.list_name] = diff.fetched

    overrides["updated_at"] = report.timestamp.isoformat()

    # Write override file
    override_path.write_text(json.dumps(overrides, indent=2, ensure_ascii=False), encoding="utf-8")

    # Append audit log entry
    audit_entry = {
        "timestamp": report.timestamp.isoformat(),
        "changes": {
            d.list_name: {"added": d.added, "removed": d.removed}
            for d in report.diffs if d.has_changes
        },
        "errors": report.fetch_errors,
    }
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(audit_entry, ensure_ascii=False) + "\n")

    logger.info("Reference data override written to %s", override_path)
    return override_path


def check_staleness(max_age_days: int = 7) -> str | None:
    """Check if screening list overrides are stale or missing.

    Returns a warning string if >max_age_days old or missing, else None.
    No network calls — just a local file stat.
    """
    override_path = _SCREENING_LISTS_DIR / "reference_data_override.json"
    if not override_path.exists():
        return (
            "Screening list overrides not found. Run --update-lists to fetch "
            "the latest FATF/OFAC/FINTRAC reference data."
        )
    mtime = datetime.fromtimestamp(override_path.stat().st_mtime)
    age = datetime.now() - mtime
    if age.days > max_age_days:
        return (
            f"Screening list overrides are {age.days} days old (last updated {mtime:%Y-%m-%d}). "
            f"Run --update-lists to refresh."
        )
    return None
