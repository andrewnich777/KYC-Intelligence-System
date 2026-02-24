"""
Entity Sanctions Screening Agent.
Entity screening + OFAC 50% rule.
"""

from agents.base import BaseAgent, load_prompt_template
from logger import get_logger
from models import Confidence, DispositionStatus, EvidenceClass, SanctionsResult

logger = get_logger(__name__)


class EntitySanctionsAgent(BaseAgent):
    """Screen business entities against sanctions lists with OFAC 50% rule."""

    @property
    def name(self) -> str:
        return "EntitySanctions"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("entity_sanctions")

    @property
    def tools(self) -> list[str]:
        return ["web_search", "screening_list_lookup", "web_fetch"]

    async def research(self, legal_name: str, beneficial_owners: list = None,
                       countries: list = None, us_nexus: bool = False,
                       ) -> SanctionsResult:
        """Screen a business entity against sanctions lists."""
        ubo_section = ""
        if beneficial_owners:
            ubo_lines = []
            for ubo in beneficial_owners:
                name = ubo.get("full_name", ubo) if isinstance(ubo, dict) else str(ubo)
                pct = ubo.get("ownership_percentage", "?") if isinstance(ubo, dict) else "?"
                ubo_lines.append(f"  - {name} ({pct}%)")
            ubo_section = "\nBeneficial Owners:\n" + "\n".join(ubo_lines)
            ubo_section += "\n\nIMPORTANT: Check OFAC 50% rule — if any owner with >=50% is SDN-listed, the entity is BLOCKED."

        ofac_msg = "Search OFAC SDN list specifically (US nexus present)" if us_nexus else "Check OFAC SDN if relevant"
        countries_str = ", ".join(countries or ["Not provided"])

        prompt = f"""Screen this business entity against sanctions lists:

Entity: {legal_name}
Countries of Operation: {countries_str}
US Nexus: {us_nexus}""" + ubo_section + f"""

Steps:
1. Search Consolidated Screening List for entity name and aliases
2. Search OpenSanctions for the entity
3. {ofac_msg}
4. Check if any beneficial owners trigger the 50% rule
5. Document all findings with evidence"""

        result = await self.run(prompt)
        return self._parse_result(result, legal_name, beneficial_owners)

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

    def _parse_result(self, result: dict, entity_name: str,
                      beneficial_owners: list = None) -> SanctionsResult:
        data = result.get("json", {})
        if not data:
            text = result.get("text", "")
            clear_signals = ["no match", "no result", "not found", "no sanctioned",
                             "cleared", "no sanctions", "no hits", "does not appear"]
            text_lower = text.lower()
            is_clear = any(s in text_lower for s in clear_signals)
            disposition = DispositionStatus.CLEAR if is_clear else DispositionStatus.PENDING_REVIEW
            reasoning = ("Agent screening completed — no entity sanctions matches identified"
                         if is_clear else
                         "Agent did not return structured data — manual review required")
            clear_record = self._build_clear_record(
                "san_ent_clear", entity_name,
                "Entity sanctions screening completed — no matches found" if is_clear
                else "Entity sanctions screening completed — results require manual review",
                [{"sources_checked": ["CSL", "OpenSanctions", "Canadian SEMA", "UN SCSL", "Global Affairs Canada"]}],
                disposition_reasoning=reasoning,
            )
            if not is_clear:
                clear_record.evidence_level = EvidenceClass.INFERRED
                clear_record.disposition = DispositionStatus.PENDING_REVIEW
                clear_record.confidence = Confidence.MEDIUM
            sr = SanctionsResult(
                entity_screened=entity_name,
                disposition=disposition,
                disposition_reasoning=reasoning,
                evidence_records=[clear_record],
            )
            self._attach_search_queries(sr, result)
            self._attach_fetched_urls(sr.evidence_records, result)
            return sr

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
            urls = match_urls or fetched
            records.append(self._build_finding_record(
                f"san_ent_{i}", entity_name,
                f"Entity sanctions match: {match.get('matched_name', 'unknown')}",
                [match],
                source_urls=urls,
            ))

        if not records:
            screening_sources = data.get("screening_sources", [])
            records.append(self._build_clear_record(
                "san_ent_clear", entity_name,
                "No entity sanctions matches found",
                [{"sources_checked": screening_sources or ["CSL", "OpenSanctions", "Canadian SEMA", "UN SCSL"]}],
                source_urls=fetched,
            ))

        # Deterministic OFAC 50% rule validation:
        # If any match references a UBO with >=50% ownership, set flag
        ofac_50_applicable = data.get("ofac_50_percent_rule_applicable", False)
        if not ofac_50_applicable and beneficial_owners and data.get("matches"):
            matched_names = {
                (m.get("matched_name") or "").lower() for m in data.get("matches", [])
            }
            for ubo in beneficial_owners:
                ubo_name = (ubo.get("full_name", ubo) if isinstance(ubo, dict)
                            else getattr(ubo, "full_name", str(ubo))).lower()
                ubo_pct = (ubo.get("ownership_percentage", 0) if isinstance(ubo, dict)
                           else getattr(ubo, "ownership_percentage", 0))
                if ubo_pct >= 50 and any(ubo_name in mn or mn in ubo_name
                                         for mn in matched_names if mn):
                    ofac_50_applicable = True
                    break

        # Build evidence record for OFAC 50% rule applicability
        if ofac_50_applicable:
            records.append(self._build_finding_record(
                "san_ent_ofac50", entity_name,
                "OFAC 50% rule applicable — entity may be treated as sanctioned via UBO ownership",
                [{"ofac_50_percent_rule_applicable": True}],
                source_urls=fetched,
            ))

        screening_sources = data.get("screening_sources", [])
        if not screening_sources:
            screening_sources = self._infer_screening_sources()

        disposition = self._derive_disposition(records)

        sr = SanctionsResult(
            entity_screened=data.get("entity_screened", entity_name),
            screening_sources=screening_sources,
            matches=data.get("matches", []),
            disposition=disposition,
            disposition_reasoning=data.get("disposition_reasoning", ""),
            ofac_50_percent_rule_applicable=ofac_50_applicable,
            evidence_records=records,
        )
        self._attach_search_queries(sr, result)
        self._attach_fetched_urls(sr.evidence_records, result)
        return sr
