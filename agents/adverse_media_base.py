"""
Shared mixin for adverse media parsing logic.

The individual and business adverse media agents have ~95% identical
_parse_result methods. This mixin extracts the shared parsing logic.
"""

from agents.base import _safe_parse_enum
from models import AdverseMediaLevel, AdverseMediaResult, Confidence, DispositionStatus, EvidenceClass, EvidenceRecord


class AdverseMediaParserMixin:
    """Mixin providing shared adverse media result parsing."""

    def _parse_adverse_media_result(
        self,
        result: dict,
        entity_name: str,
        id_prefix: str,
        claim_prefix: str,
    ) -> AdverseMediaResult:
        """
        Parse agent response into AdverseMediaResult.

        Args:
            result: Raw result dict from agent.run()
            entity_name: Name of the entity screened
            id_prefix: Evidence ID prefix (e.g. "adv_ind" or "adv_biz")
            claim_prefix: Claim prefix (e.g. "Adverse media" or "Business adverse media")
        """
        data = result.get("json", {})
        if not data:
            # Check text for clear signals before defaulting
            text = result.get("text", "").lower()
            clear_signals = ["no adverse", "no negative", "no derogatory",
                             "no media findings", "clean media profile"]
            is_clear = any(s in text for s in clear_signals)
            if is_clear:
                record = self._build_clear_record(
                    f"{id_prefix}_clear", entity_name,
                    f"No {claim_prefix.lower()} found",
                    disposition_reasoning="Agent prose indicates no adverse media found",
                )
                level = AdverseMediaLevel.CLEAR
            else:
                record = EvidenceRecord(
                    evidence_id=f"{id_prefix}_no_json",
                    source_type="agent",
                    source_name=getattr(self, 'name', 'AdverseMedia'),
                    entity_screened=entity_name,
                    claim=f"{claim_prefix} screening completed — agent did not return structured data",
                    evidence_level=EvidenceClass.INFERRED,
                    disposition=DispositionStatus.PENDING_REVIEW,
                    confidence=Confidence.LOW,
                    disposition_reasoning="Agent did not return structured data and prose lacks clear signals — manual review required",
                )
                level = AdverseMediaLevel.LOW_CONCERN
            amr = AdverseMediaResult(
                entity_screened=entity_name,
                overall_level=level,
                evidence_records=[record],
            )
            self._attach_search_queries(amr, result)
            self._attach_fetched_urls(amr.evidence_records, result)
            return amr

        level = _safe_parse_enum(
            AdverseMediaLevel,
            data.get("overall_level", "CLEAR"),
            AdverseMediaLevel.CLEAR,
        )

        records = []
        fetched = list(getattr(self, '_fetched_urls', None) or [])
        for i, article in enumerate(data.get("articles_found", [])):
            # Extract article-specific URLs
            article_urls = []
            if isinstance(article, dict):
                for key in ("url", "source_url", "link"):
                    if article.get(key):
                        article_urls.append(article[key])
            records.append(self._build_finding_record(
                f"{id_prefix}_{i}", entity_name,
                f"{claim_prefix}: {article.get('title', 'Unknown')}",
                [article],
                source_urls=article_urls or fetched,
            ))

        if not records:
            records.append(self._build_clear_record(
                f"{id_prefix}_clear", entity_name,
                f"No {claim_prefix.lower()} found",
            ))

        # Cross-check: if all evidence records are CLEAR, override level
        if records and all(
            getattr(r, 'disposition', None) == DispositionStatus.CLEAR for r in records
        ):
            level = AdverseMediaLevel.CLEAR
        # Bidirectional: if AI says CLEAR but evidence has non-CLEAR records, elevate
        elif level == AdverseMediaLevel.CLEAR and records and any(
            getattr(r, 'disposition', DispositionStatus.CLEAR) != DispositionStatus.CLEAR
            for r in records
        ):
            level = AdverseMediaLevel.LOW_CONCERN

        amr = AdverseMediaResult(
            entity_screened=data.get("entity_screened", entity_name),
            overall_level=level,
            articles_found=data.get("articles_found", []),
            categories=data.get("categories", []),
            evidence_records=records,
        )
        self._attach_search_queries(amr, result)
        self._attach_fetched_urls(amr.evidence_records, result)
        return amr
