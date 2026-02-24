"""
Within-document deduplication utilities.

Provides hash-based deduplication for quotes, claims, and evidence blocks
within a single brief. Cross-brief duplication is intentional and preserved.
"""

import hashlib
from typing import Any


def deduplicate_items(items: list[str], seen_hashes: set[str] | None = None) -> list[str]:
    """
    Remove exact duplicate strings from a list.

    Args:
        items: List of strings to deduplicate
        seen_hashes: Optional set to track hashes across multiple calls
                    (pass the same set to dedupe across sections within one brief)

    Returns:
        List with duplicates removed, preserving original formatting
    """
    if seen_hashes is None:
        seen_hashes = set()

    unique_items = []
    for item in items:
        if not item:
            continue
        # Normalize: strip whitespace, lowercase for comparison
        normalized = item.strip().lower()
        item_hash = hashlib.md5(normalized.encode()).hexdigest()

        if item_hash not in seen_hashes:
            seen_hashes.add(item_hash)
            unique_items.append(item)  # Keep original formatting

    return unique_items


def deduplicate_claims(claims: list[Any], seen_hashes: set[str] | None = None) -> list[Any]:
    """
    Remove duplicate claims based on claim text.

    Works with Claim objects or any object with a 'claim' attribute.

    Args:
        claims: List of Claim objects to deduplicate
        seen_hashes: Optional set to track hashes across multiple calls

    Returns:
        List with duplicate claims removed
    """
    if seen_hashes is None:
        seen_hashes = set()

    unique_claims = []
    for claim in claims:
        if claim is None:
            continue

        # Get claim text from object or use string representation
        claim_text = getattr(claim, 'claim', str(claim))
        if not claim_text:
            continue

        normalized = claim_text.strip().lower()
        claim_hash = hashlib.md5(normalized.encode()).hexdigest()

        if claim_hash not in seen_hashes:
            seen_hashes.add(claim_hash)
            unique_claims.append(claim)

    return unique_claims


def deduplicate_by_field(items: list[Any], field: str, seen_hashes: set[str] | None = None) -> list[Any]:
    """
    Remove duplicates based on a specific field value.

    Useful for deduplicating objects by name, title, url, etc.

    Args:
        items: List of objects to deduplicate
        field: Name of the field to use for comparison
        seen_hashes: Optional set to track hashes across multiple calls

    Returns:
        List with duplicates removed based on field value
    """
    if seen_hashes is None:
        seen_hashes = set()

    unique_items = []
    for item in items:
        if item is None:
            continue

        # Get field value
        field_value = getattr(item, field, None)
        if field_value is None:
            # If field doesn't exist, include item anyway
            unique_items.append(item)
            continue

        normalized = str(field_value).strip().lower()
        item_hash = hashlib.md5(normalized.encode()).hexdigest()

        if item_hash not in seen_hashes:
            seen_hashes.add(item_hash)
            unique_items.append(item)

    return unique_items


def deduplicate_evidence_urls(claims: list[Any], seen_hashes: set[str] | None = None) -> list[Any]:
    """
    Remove claims that have duplicate evidence URLs.

    Useful when the same source is cited multiple times with slight variations.

    Args:
        claims: List of Claim objects with evidence
        seen_hashes: Optional set to track hashes across multiple calls

    Returns:
        List with claims having duplicate evidence URLs removed
    """
    if seen_hashes is None:
        seen_hashes = set()

    unique_claims = []
    for claim in claims:
        if claim is None:
            continue

        # Get first evidence URL if available
        evidence = getattr(claim, 'evidence', [])
        if evidence and len(evidence) > 0:
            url = getattr(evidence[0], 'url', '')
            if url:
                normalized = url.strip().lower()
                url_hash = hashlib.md5(normalized.encode()).hexdigest()

                if url_hash in seen_hashes:
                    continue  # Skip claim with duplicate evidence URL
                seen_hashes.add(url_hash)

        unique_claims.append(claim)

    return unique_claims


class BriefDeduplicator:
    """
    Context manager for deduplicating within a single document.

    Usage:
        with BriefDeduplicator() as dedup:
            unique_findings = dedup.claims(sanctions_evidence)
            unique_media = dedup.claims(adverse_media_evidence)
            # Both share the same seen_hashes set
    """

    def __init__(self):
        self.seen_hashes: set[str] = set()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.seen_hashes.clear()
        return False

    def items(self, items: list[str]) -> list[str]:
        """Deduplicate string items."""
        return deduplicate_items(items, self.seen_hashes)

    def claims(self, claims: list[Any]) -> list[Any]:
        """Deduplicate Claim objects."""
        return deduplicate_claims(claims, self.seen_hashes)

    def by_field(self, items: list[Any], field: str) -> list[Any]:
        """Deduplicate by specific field."""
        return deduplicate_by_field(items, field, self.seen_hashes)

    def by_url(self, claims: list[Any]) -> list[Any]:
        """Deduplicate by evidence URL."""
        return deduplicate_evidence_urls(claims, self.seen_hashes)
