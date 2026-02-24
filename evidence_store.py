"""
Queryable, deduplicated evidence collection.

Backward-compatible with list[dict] — supports append(), extend(), len(),
iteration, indexing, and bool(). Pipeline code that treats the evidence store
as a plain list continues to work unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import overload

from constants import EVIDENCE_STORE_WARN_THRESHOLD

logger = logging.getLogger(__name__)


class EvidenceStore:
    """Queryable, deduplicated evidence collection."""

    def __init__(self, records: list[dict] | None = None):
        self._records: list[dict] = []
        self._seen_ids: set[str] = set()
        if records:
            self.extend(records)

    # --------------------------------------------------------------------- #
    # Core mutation
    # --------------------------------------------------------------------- #

    def add(self, record: dict) -> bool:
        """Add a record, deduplicating by evidence_id.

        Validates and auto-downgrades evidence_level when unsupported:
        - V without source_urls → downgraded to S
        - V or S without supporting_data → downgraded to I

        Returns True if the record was new (added), False if duplicate.
        """
        eid = record.get("evidence_id", "")
        if not eid:
            logger.warning("Evidence record added without evidence_id — deduplication bypassed (claim: %s)",
                           str(record.get("claim", ""))[:80])
        if eid and eid in self._seen_ids:
            return False

        # Validate and downgrade evidence level when unsupported
        level = record.get("evidence_level", "")
        urls = record.get("source_urls", [])
        data = record.get("supporting_data", [])

        if level == "V" and not urls:
            logger.warning(
                "Evidence %s has level VERIFIED but no source_urls — downgrading to SOURCED", eid
            )
            record["evidence_level"] = "S"
            level = "S"
        if level in ("V", "S") and not data:
            logger.warning(
                "Evidence %s has level %s but no supporting_data — downgrading to INFERRED", eid, level
            )
            record["evidence_level"] = "I"

        if eid:
            self._seen_ids.add(eid)
        self._records.append(record)
        if len(self._records) == EVIDENCE_STORE_WARN_THRESHOLD:
            logger.warning(
                "Evidence store reached %d records — investigation may be unusually broad",
                EVIDENCE_STORE_WARN_THRESHOLD,
            )
        return True

    def append(self, record: dict) -> None:
        """Alias for add() — list compatibility."""
        self.add(record)

    def extend(self, records: list[dict] | EvidenceStore) -> None:
        """Batch add — list compatibility."""
        for r in records:
            self.add(r)

    def remove_by_source(self, source_name: str) -> int:
        """Remove all records from a given source (e.g., agent name).

        Used during reinvestigation to purge stale records before appending
        fresh ones from the re-run agent.  Returns the count of records removed.
        Matching is case-insensitive to stay consistent with query().
        """
        before = len(self._records)
        source_lower = source_name.lower()
        removed_ids = {
            r.get("evidence_id") for r in self._records
            if r.get("source_name", "").lower() == source_lower and r.get("evidence_id")
        }
        self._records = [
            r for r in self._records
            if r.get("source_name", "").lower() != source_lower
        ]
        self._seen_ids -= removed_ids
        return before - len(self._records)

    # --------------------------------------------------------------------- #
    # Query
    # --------------------------------------------------------------------- #

    def query(
        self,
        *,
        entity: str | None = None,
        source: str | None = None,
        disposition: str | None = None,
    ) -> list[dict]:
        """Filter records by entity, source, and/or disposition."""
        results = self._records
        if entity is not None:
            entity_lower = entity.lower()
            results = [r for r in results if r.get("entity_screened", "").lower() == entity_lower]
        if source is not None:
            source_lower = source.lower()
            results = [r for r in results if r.get("source_name", "").lower() == source_lower]
        if disposition is not None:
            disp_upper = disposition.upper()
            results = [r for r in results if r.get("disposition", "").upper() == disp_upper]
        return results

    def by_disposition(self) -> dict[str, list[dict]]:
        """Group records by disposition status."""
        groups: dict[str, list[dict]] = {}
        for r in self._records:
            disp = r.get("disposition", "UNKNOWN")
            groups.setdefault(disp, []).append(r)
        return groups

    def conflicts(self) -> list[tuple[dict, dict]]:
        """Find CLEAR vs MATCH conflicts for the same entity."""
        entity_disps: dict[str, list[dict]] = {}
        for r in self._records:
            entity = r.get("entity_screened", "").lower()
            if entity:
                entity_disps.setdefault(entity, []).append(r)

        conflict_pairs: list[tuple[dict, dict]] = []
        for _entity, records in entity_disps.items():
            clears = [r for r in records if r.get("disposition") == "CLEAR"]
            matches = [
                r for r in records
                if r.get("disposition") in ("POTENTIAL_MATCH", "CONFIRMED_MATCH")
            ]
            for c in clears:
                for m in matches:
                    conflict_pairs.append((c, m))
        return conflict_pairs

    # --------------------------------------------------------------------- #
    # Aggregation
    # --------------------------------------------------------------------- #

    def count_by_level(self) -> dict[str, int]:
        """Return evidence counts grouped by level (V, S, I, U)."""
        counts = {"V": 0, "S": 0, "I": 0, "U": 0}
        for r in self._records:
            level = r.get("evidence_level", "U")
            if level in counts:
                counts[level] += 1
            else:
                counts["U"] += 1
        return counts

    def compute_evidence_graph(self):
        """Return a KYCEvidenceGraph computed from records."""
        from models import KYCEvidenceGraph
        counts = self.count_by_level()
        return KYCEvidenceGraph(
            total_evidence_records=len(self._records),
            verified_count=counts["V"],
            sourced_count=counts["S"],
            inferred_count=counts["I"],
            unknown_count=counts["U"],
        )

    # --------------------------------------------------------------------- #
    # Serialization
    # --------------------------------------------------------------------- #

    def all(self) -> list[dict]:
        """Return all records as a list."""
        return list(self._records)

    def to_list(self) -> list[dict]:
        """For JSON serialization — returns a plain list."""
        return list(self._records)

    def to_redacted_list(self) -> list[dict]:
        """Return records with PII fields masked — for debug output and web APIs."""
        from utilities.pii_sanitizer import sanitize_dict
        return [sanitize_dict(r) for r in self._records]

    # --------------------------------------------------------------------- #
    # list-like interface
    # --------------------------------------------------------------------- #

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[dict]:
        return iter(self._records)

    @overload
    def __getitem__(self, index: int) -> dict: ...

    @overload
    def __getitem__(self, index: slice) -> list[dict]: ...

    def __getitem__(self, index: int | slice) -> dict | list[dict]:
        return self._records[index]

    def __bool__(self) -> bool:
        return len(self._records) > 0

    def __repr__(self) -> str:
        return f"EvidenceStore({len(self._records)} records)"
