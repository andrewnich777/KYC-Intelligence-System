"""
Individual Sanctions Screening Agent.
Screens individuals against CSL, OpenSanctions, Canadian sanctions, UN list.
"""

from agents.base import BaseAgent, load_prompt_template
from logger import get_logger
from models import Confidence, DispositionStatus, EvidenceClass, EvidenceRecord, SanctionsResult

logger = get_logger(__name__)


class IndividualSanctionsAgent(BaseAgent):
    """Screen individual names against sanctions lists."""

    @property
    def name(self) -> str:
        return "IndividualSanctions"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("individual_sanctions")

    @property
    def tools(self) -> list[str]:
        return ["web_search", "screening_list_lookup", "web_fetch"]

    async def research(self, full_name: str, date_of_birth: str = None,
                       citizenship: str = None, context: str = None) -> SanctionsResult:
        """Screen an individual against sanctions lists."""
        prompt = f"""Screen this individual against all available sanctions lists:

Name: {full_name}
Date of Birth: {date_of_birth or 'Not provided'}
Citizenship: {citizenship or 'Not provided'}
Context: {context or 'Primary account holder'}

Steps:
1. Search the Consolidated Screening List for name matches
2. Search OpenSanctions database for the name
3. Search Canadian SEMA (Special Economic Measures Act) sanctions
4. Search UN Security Council consolidated list
5. For any potential matches, verify using secondary identifiers (DOB, citizenship)
6. Classify each match and provide disposition

Be thorough but precise. Common names will have many results — focus on identifying the RIGHT person."""

        result = await self.run(prompt)
        return self._parse_result(result, full_name)

    def _parse_result(self, result: dict, entity_name: str) -> SanctionsResult:
        """Parse agent response into SanctionsResult."""
        data = result.get("json", {})
        if not data:
            # Agent completed but didn't return JSON — build evidence from text response
            text = result.get("text", "")
            # If the agent's prose indicates no matches, treat as clear
            clear_signals = ["no match", "no result", "not found", "no sanctioned",
                             "cleared", "no sanctions", "no hits", "does not appear"]
            text_lower = text.lower()
            is_clear = any(s in text_lower for s in clear_signals)
            disposition = DispositionStatus.CLEAR if is_clear else DispositionStatus.PENDING_REVIEW
            reasoning = ("Agent screening completed — no sanctions matches identified"
                         if is_clear else
                         "Agent did not return structured data — manual review required")
            clear_record = EvidenceRecord(
                evidence_id="san_ind_clear",
                source_type="agent",
                source_name=self.name,
                entity_screened=entity_name,
                claim="Sanctions screening completed — no matches found" if is_clear else "Sanctions screening completed — results require manual review",
                evidence_level=EvidenceClass.SOURCED if is_clear else EvidenceClass.INFERRED,
                supporting_data=[{"sources_checked": ["CSL", "OpenSanctions", "Canadian SEMA", "UN SCSL", "Global Affairs Canada"]}],
                disposition=disposition,
                disposition_reasoning=reasoning,
                confidence=Confidence.HIGH if is_clear else Confidence.MEDIUM,
            )
            sr = SanctionsResult(
                entity_screened=entity_name,
                screening_sources=["CSL", "OpenSanctions", "Canadian SEMA", "UN SCSL", "Global Affairs Canada"],
                disposition=disposition,
                disposition_reasoning=reasoning,
                evidence_records=[clear_record],
            )
            self._attach_search_queries(sr, result)
            self._attach_fetched_urls(sr.evidence_records, result)
            return sr

        screening_sources = data.get("screening_sources", [])
        if not screening_sources:
            screening_sources = self._infer_screening_sources()

        records = self._build_evidence_records(data, entity_name, screening_sources)
        disposition = self._derive_disposition(records)

        sr = SanctionsResult(
            entity_screened=data.get("entity_screened", entity_name),
            screening_sources=screening_sources,
            matches=data.get("matches", []),
            disposition=disposition,
            disposition_reasoning=data.get("disposition_reasoning", ""),
            evidence_records=records,
        )
        self._attach_search_queries(sr, result)
        self._attach_fetched_urls(sr.evidence_records, result)
        return sr

    def _infer_screening_sources(self) -> list[str]:
        """Infer which screening sources were checked from fetched URLs."""
        sources = []
        url_source_map = {
            "opensanctions.org": "OpenSanctions",
            "sanctionssearch.ofac.treas.gov": "OFAC SDN",
            "ofac.treasury.gov": "OFAC SDN",
            "international.gc.ca": "Canadian SEMA",
            "scsanctions.un.org": "UN SCSL",
            "api.trade.gov": "Trade.gov CSL",
            "offshoreleaks.icij.org": "ICIJ Offshore Leaks",
            "data.europa.eu": "EU Consolidated Sanctions",
            "gov.uk": "UK HMT Sanctions",
            "interpol.int": "Interpol Red Notices",
            "fca.org.uk": "FCA Warning List",
        }
        seen = set()
        for url in self._fetched_urls:
            for domain, source_name in url_source_map.items():
                if domain in url and source_name not in seen:
                    sources.append(source_name)
                    seen.add(source_name)
        return sources or ["CSL", "OpenSanctions", "Canadian SEMA", "UN SCSL", "Global Affairs Canada"]

    def _build_evidence_records(self, data: dict, entity_name: str,
                                screening_sources: list[str] = None) -> list[EvidenceRecord]:
        """Build evidence records from parsed data."""
        records = []
        fetched = list(self._fetched_urls) if self._fetched_urls else []

        for i, match in enumerate(data.get("matches", [])):
            # Extract claim-specific URL from match details if available
            match_urls = []
            details = match.get("details", {})
            if isinstance(details, dict):
                for key in ("url", "source_url", "link"):
                    if details.get(key):
                        match_urls.append(details[key])
            # Fall back to agent-wide fetched URLs
            urls = match_urls or fetched
            records.append(self._build_finding_record(
                f"san_ind_{i}", entity_name,
                f"Sanctions match: {match.get('matched_name', 'unknown')} on {match.get('list_name', 'unknown')}",
                [match],
                source_urls=urls,
            ))

        if not records:
            sources = screening_sources or data.get("screening_sources", [])
            records.append(self._build_clear_record(
                "san_ind_clear", entity_name,
                "No sanctions matches found across all screening sources",
                [{"sources_checked": sources}],
                disposition_reasoning=data.get("disposition_reasoning", "No matches"),
                source_urls=fetched,
            ))

        return records
