"""
Transaction Monitoring Agent.
Researches AML typologies, enforcement actions, and monitoring thresholds
for a client's industry and geographic profile.
"""

from agents.base import BaseAgent, load_prompt_template
from logger import get_logger
from models import (
    AMLTypology,
    Confidence,
    DispositionStatus,
    EvidenceClass,
    EvidenceRecord,
    TransactionMonitoringResult,
)

logger = get_logger(__name__)


class TransactionMonitoringAgent(BaseAgent):
    """Research AML typologies and monitoring requirements for a client profile."""

    @property
    def name(self) -> str:
        return "TransactionMonitoring"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("transaction_monitoring")

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(
        self,
        entity_name: str,
        industry: str = None,
        countries: list[str] = None,
        expected_volume: float = None,
        expected_frequency: str = None,
        account_requests: list[dict] = None,
        source_of_funds: str = None,
    ) -> TransactionMonitoringResult:
        """Research AML typologies and monitoring thresholds for a client profile."""
        countries_str = ", ".join(countries or ["Canada"])
        account_lines = ""
        if account_requests:
            acct_strs = []
            for acct in account_requests:
                if isinstance(acct, dict):
                    acct_strs.append(f"  - {acct.get('account_type', 'unknown')}")
                else:
                    acct_strs.append(f"  - {acct}")
            account_lines = "\nAccount Types Requested:\n" + "\n".join(acct_strs)

        prompt = f"""Assess AML/transaction monitoring requirements for this client:

Entity: {entity_name}
Industry: {industry or 'Not specified'}
Countries of Operation: {countries_str}
Expected Transaction Volume: {expected_volume or 'Not specified'}
Expected Transaction Frequency: {expected_frequency or 'Not specified'}
Source of Funds: {source_of_funds or 'Not specified'}{account_lines}

Research:
1. Industry-specific AML typologies relevant to {industry or 'this entity'}
2. Country-specific ML/TF methodologies for {countries_str}
3. Recent FINTRAC/FinCEN enforcement actions in this sector
4. Profile-specific red flags and monitoring thresholds
5. Recommended alert parameters and monitoring frequency

Return JSON with industry_typologies, geographic_typologies, recommended_alerts,
recommended_monitoring_frequency, and sar_risk_indicators."""

        result = await self.run(prompt)
        return self._parse_result(result, entity_name)

    def _parse_result(self, result: dict, entity_name: str) -> TransactionMonitoringResult:
        """Parse agent response into TransactionMonitoringResult."""
        data = result.get("json", {})
        if not data:
            # Check text for clear signals before defaulting
            text = result.get("text", "").lower()
            clear_signals = ["standard monitoring", "no elevated", "low risk",
                             "routine monitoring", "no unusual"]
            is_clear = any(s in text for s in clear_signals)
            if is_clear:
                record = self._build_clear_record(
                    "txn_mon_clear", entity_name,
                    "Transaction monitoring assessment completed — standard monitoring recommended",
                    disposition_reasoning="Agent prose indicates standard monitoring",
                )
            else:
                record = EvidenceRecord(
                    evidence_id="txn_mon_no_json",
                    source_type="agent",
                    source_name=self.name,
                    entity_screened=entity_name,
                    claim="Transaction monitoring assessment completed — agent did not return structured data",
                    evidence_level=EvidenceClass.INFERRED,
                    disposition=DispositionStatus.PENDING_REVIEW,
                    confidence=Confidence.LOW,
                    disposition_reasoning="Agent did not return structured data and prose lacks clear signals — manual review required",
                )
            tmr = TransactionMonitoringResult(
                entity_screened=entity_name,
                evidence_records=[record],
            )
            self._attach_search_queries(tmr, result)
            self._attach_fetched_urls(tmr.evidence_records, result)
            return tmr

        # Parse typologies
        industry_typologies = []
        for t in data.get("industry_typologies", []):
            if isinstance(t, dict):
                industry_typologies.append(AMLTypology(
                    typology_name=t.get("typology_name", t.get("name", "Unknown")),
                    description=t.get("description", ""),
                    relevance=t.get("relevance", "MEDIUM"),
                    indicators=t.get("indicators", []),
                    monitoring_recommendation=t.get("monitoring_recommendation", ""),
                ))

        geographic_typologies = []
        for t in data.get("geographic_typologies", []):
            if isinstance(t, dict):
                geographic_typologies.append(AMLTypology(
                    typology_name=t.get("typology_name", t.get("name", "Unknown")),
                    description=t.get("description", ""),
                    relevance=t.get("relevance", "MEDIUM"),
                    indicators=t.get("indicators", []),
                    monitoring_recommendation=t.get("monitoring_recommendation", ""),
                ))

        # Build evidence records
        records = []
        all_typologies = industry_typologies + geographic_typologies
        if all_typologies:
            high_relevance = [t for t in all_typologies if t.relevance == "HIGH"]
            records.append(self._build_finding_record(
                "txn_mon_0", entity_name,
                f"Transaction monitoring: {len(all_typologies)} AML typologies identified, "
                f"{len(high_relevance)} high-relevance",
                [{"typology_count": len(all_typologies), "high_relevance_count": len(high_relevance)}],
            ))
        else:
            records.append(self._build_clear_record(
                "txn_mon_clear", entity_name,
                "Transaction monitoring: no elevated AML typologies identified",
            ))

        tmr = TransactionMonitoringResult(
            entity_screened=data.get("entity_screened", entity_name),
            industry_typologies=industry_typologies,
            geographic_typologies=geographic_typologies,
            recommended_alerts=data.get("recommended_alerts", []),
            recommended_monitoring_frequency=data.get("recommended_monitoring_frequency", "standard"),
            sar_risk_indicators=data.get("sar_risk_indicators", []),
            evidence_records=records,
        )
        self._attach_search_queries(tmr, result)
        self._attach_fetched_urls(tmr.evidence_records, result)
        return tmr
